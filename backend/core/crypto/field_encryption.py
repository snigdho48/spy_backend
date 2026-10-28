"""Application-level Fernet encryption for sensitive JSON payload fields.

Design (migration-safe for existing plaintext rows):
- New writes encrypt selected string fields when FIELD_ENCRYPTION_KEY is set.
- Reads decrypt values that look like our ciphertext; plaintext is returned as-is.
- No DB schema change; values live inside existing JSON columns.
- Production fails closed if the key is missing (see settings/prod.py).
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

# Prefix so we can distinguish ciphertext from coincidental base64 plaintext.
_PREFIX = "enc:v1:"

# Scalar string keys encrypted in event / notification / message payloads.
SENSITIVE_SCALAR_KEYS = frozenset(
    {
        "body",
        "text",
        "preview",
        "message",
        "phone",
        "phone_number",
        "number",
        "from",
        "to",
        "msisdn",
    }
)

# List-of-strings keys (e.g. contact phones).
SENSITIVE_LIST_KEYS = frozenset(
    {
        "phones",
        "numbers",
        "phone_numbers",
    }
)


def _fernet():
    key = (getattr(settings, "FIELD_ENCRYPTION_KEY", "") or "").strip()
    if not key:
        return None
    from cryptography.fernet import Fernet

    try:
        return Fernet(key.encode("ascii") if isinstance(key, str) else key)
    except Exception:
        logger.exception("Invalid FIELD_ENCRYPTION_KEY")
        raise


def is_encryption_enabled() -> bool:
    return bool((getattr(settings, "FIELD_ENCRYPTION_KEY", "") or "").strip())


def encrypt_str(value: str) -> str:
    if not value or value.startswith(_PREFIX):
        return value
    f = _fernet()
    if f is None:
        return value
    token = f.encrypt(value.encode("utf-8")).decode("ascii")
    return f"{_PREFIX}{token}"


def decrypt_str(value: str) -> str:
    if not value or not value.startswith(_PREFIX):
        return value
    f = _fernet()
    if f is None:
        # Key missing: return ciphertext rather than crashing a read path.
        return value
    from cryptography.fernet import InvalidToken

    token = value[len(_PREFIX) :]
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.warning("Failed to decrypt field value (wrong key or corrupt)")
        return value


def encrypt_payload(payload: dict | None) -> dict:
    """Return a copy of *payload* with sensitive fields encrypted for storage."""
    if not payload or not is_encryption_enabled():
        return dict(payload or {})
    return _transform(dict(payload), encrypt=True)


def decrypt_payload(payload: dict | None) -> dict:
    """Return a copy of *payload* with sensitive fields decrypted for API responses."""
    if not payload:
        return {}
    if not is_encryption_enabled():
        # Still strip prefix if somehow present without a key — leave as-is.
        return dict(payload)
    return _transform(dict(payload), encrypt=False)


def encrypt_contacts(contacts: list | None) -> list:
    if not contacts or not is_encryption_enabled():
        return list(contacts or [])
    return [_transform(dict(c), encrypt=True) if isinstance(c, dict) else c for c in contacts]


def decrypt_contacts(contacts: list | None) -> list:
    if not contacts:
        return []
    if not is_encryption_enabled():
        return list(contacts)
    return [
        _transform(dict(c), encrypt=False) if isinstance(c, dict) else c for c in contacts
    ]


def _transform(obj: dict, *, encrypt: bool) -> dict:
    fn = encrypt_str if encrypt else decrypt_str
    out: dict[str, Any] = {}
    for key, value in obj.items():
        if key in SENSITIVE_SCALAR_KEYS and isinstance(value, str):
            out[key] = fn(value)
        elif key in SENSITIVE_LIST_KEYS and isinstance(value, list):
            out[key] = [fn(v) if isinstance(v, str) else v for v in value]
        elif key == "contacts" and isinstance(value, list):
            out[key] = [
                _transform(dict(item), encrypt=encrypt)
                if isinstance(item, dict)
                else item
                for item in value
            ]
        elif isinstance(value, dict):
            out[key] = _transform(value, encrypt=encrypt)
        else:
            out[key] = value
    return out
