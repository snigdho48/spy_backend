"""Contact metadata on call.* / sms.* payloads. No photo fetching (SSRF)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

MAX_CONTACT_NAME = 128
MAX_PHOTO_URL = 2048
CONTACT_EVENT_PREFIXES = ("call.", "sms.")
CONTACT_BOOL_FIELDS = ("is_known", "is_flagged", "is_redacted")
REDACTED_TEXT_KEYS = ("body", "text", "preview", "message")

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def strip_control_chars(value: str) -> str:
    return _CONTROL_CHARS.sub("", value)


def apply_contact_redaction(payload: dict) -> dict:
    """When is_redacted, clear message body fields. Does not touch photo URLs."""
    out = dict(payload)
    if out.get("is_redacted") is not True:
        return out
    for key in REDACTED_TEXT_KEYS:
        if key in out:
            out[key] = ""
    return out


def normalize_https_photo_url(url: str) -> str:
    """Validate https-only photo URL. Raises ValueError on failure."""
    cleaned = strip_control_chars(url).strip()
    if len(cleaned) > MAX_PHOTO_URL:
        raise ValueError(f"Cannot exceed {MAX_PHOTO_URL} characters")
    parsed = urlparse(cleaned)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Must be an https URL (photos are not proxied)")
    if parsed.username or parsed.password:
        raise ValueError("URL must not include credentials")
    return cleaned
