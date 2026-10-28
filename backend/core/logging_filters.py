"""Log filters that redact sensitive / PII-bearing substrings."""

from __future__ import annotations

import logging
import re

# Keys commonly present in request/event dumps.
_SENSITIVE_KEY = re.compile(
    r"(?i)(\"|')?(body|text|preview|message|phone|phone_number|number|"
    r"from|to|msisdn|token|access|refresh|password|authorization|"
    r"pairing_token|pairing_code|contacts)(\"|')?\s*[:=]\s*",
)

# Capture quoted / bare values after a sensitive key up to a delimiter.
_VALUE_AFTER_KEY = re.compile(
    r"(?i)((?:body|text|preview|message|phone|phone_number|number|"
    r"from|to|msisdn|token|access_token|refresh_token|password|"
    r"authorization|pairing_token|pairing_code|Bearer)\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)",
)

# Long JWT-looking blobs.
_JWTISH = re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")

# E.164-ish phone numbers.
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\- ]{7,}\d(?!\w)")


class SensitiveDataFilter(logging.Filter):
    """Replace sensitive values in log records before they hit a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = self.redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: self.redact(v) if isinstance(v, str) else v
                        for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        self.redact(a) if isinstance(a, str) else a for a in record.args
                    )
        except Exception:
            # Never break logging.
            pass
        return True

    @staticmethod
    def redact(text: str) -> str:
        if not text:
            return text
        # "Bearer <token>" (Authorization header dumps)
        text = re.sub(
            r"(?i)\bBearer\s+[A-Za-z0-9_\-\.]+",
            "Bearer [REDACTED]",
            text,
        )
        text = _VALUE_AFTER_KEY.sub(r"\1[REDACTED]", text)
        text = _JWTISH.sub("[REDACTED_JWT]", text)
        text = _PHONE.sub("[REDACTED_PHONE]", text)
        return text
