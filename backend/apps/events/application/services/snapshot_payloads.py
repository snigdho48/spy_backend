"""Validation / normalization for contact.*, app_inventory.*, richer message.*,
and notification.* payloads. Icons and oversized blobs are stripped for TX6 RAM.
"""

from __future__ import annotations

from typing import Any

from apps.events.application.services.contact_payload import (
    MAX_CONTACT_NAME,
    strip_control_chars,
)
from apps.events.domain.event_types import (
    APP_INVENTORY_TYPES,
    CONTACT_SNAPSHOT_TYPES,
    EventTypes,
    NOTIFICATION_FEED_TYPES,
    RICH_MESSAGE_TYPES,
)

MAX_PHONE = 32
MAX_EMAIL = 254
MAX_PACKAGE = 255
MAX_APP_NAME = 128
MAX_VERSION = 64
MAX_THREAD_ID = 128
MAX_BODY = 4096
MAX_TITLE = 512
MAX_TEXT = 2048
MAX_CHANNEL = 128
MAX_CONTACTS = 2000
MAX_APPS = 500
MAX_PHONES_PER_CONTACT = 10
MAX_EMAILS_PER_CONTACT = 10

# Drop heavy / SSRF-prone keys from snapshot items before persist.
_STRIP_APP_KEYS = frozenset({"icon", "icon_base64", "icon_png", "photo", "photo_base64"})
_STRIP_CONTACT_KEYS = frozenset({"photo", "photo_base64", "thumbnail", "avatar"})

_VALID_DIRECTIONS = frozenset({"incoming", "outgoing", "unknown"})


def _clean_str(value: Any, *, max_len: int, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = strip_control_chars(value).strip()
    if len(cleaned) > max_len:
        raise ValueError(f"{field} cannot exceed {max_len} characters")
    return cleaned


def _as_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise ValueError(f"{field} must be a boolean")


def _string_list(
    value: Any, *, max_items: int, max_len: int, field: str
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if len(value) > max_items:
        raise ValueError(f"{field} cannot exceed {max_items} items")
    out: list[str] = []
    for item in value:
        if item is None:
            continue
        if not isinstance(item, (str, int)):
            raise ValueError(f"{field} items must be strings")
        cleaned = strip_control_chars(str(item)).strip()
        if not cleaned:
            continue
        if len(cleaned) > max_len:
            raise ValueError(f"{field} item cannot exceed {max_len} characters")
        out.append(cleaned)
    return out


def normalize_contact_snapshot_payload(payload: dict) -> dict:
    """Validate contact.snapshot / contact.update payloads."""
    out = dict(payload)
    raw = out.get("contacts")
    if raw is None:
        raise ValueError("contacts list is required")
    if not isinstance(raw, list):
        raise ValueError("contacts must be a list")
    if len(raw) > MAX_CONTACTS:
        raise ValueError(f"contacts cannot exceed {MAX_CONTACTS} items")

    contacts: list[dict] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"contacts[{idx}] must be an object")
        entry = {k: v for k, v in item.items() if k not in _STRIP_CONTACT_KEYS}

        name = entry.get("name") or entry.get("display_name") or entry.get("contact_name")
        if name is not None:
            entry["name"] = _clean_str(name, max_len=MAX_CONTACT_NAME, field="name")
            entry.pop("display_name", None)
            entry.pop("contact_name", None)
        else:
            entry["name"] = ""

        phones = entry.get("phones") or entry.get("numbers") or entry.get("phone_numbers")
        entry["phones"] = _string_list(
            phones,
            max_items=MAX_PHONES_PER_CONTACT,
            max_len=MAX_PHONE,
            field="phones",
        )
        entry.pop("numbers", None)
        entry.pop("phone_numbers", None)

        if "phone" in entry and entry["phone"] is not None and not entry["phones"]:
            entry["phones"] = [
                _clean_str(str(entry["phone"]), max_len=MAX_PHONE, field="phone")
            ]
        entry.pop("phone", None)

        emails = entry.get("emails") or entry.get("email_addresses")
        entry["emails"] = _string_list(
            emails,
            max_items=MAX_EMAILS_PER_CONTACT,
            max_len=MAX_EMAIL,
            field="emails",
        )
        entry.pop("email_addresses", None)
        if "email" in entry and entry["email"] is not None and not entry["emails"]:
            entry["emails"] = [
                _clean_str(str(entry["email"]), max_len=MAX_EMAIL, field="email")
            ]
        entry.pop("email", None)

        if "contact_id" in entry and entry["contact_id"] is not None:
            entry["contact_id"] = _clean_str(
                str(entry["contact_id"]), max_len=64, field="contact_id"
            )

        contacts.append(entry)

    out["contacts"] = contacts
    out["count"] = len(contacts)
    return out


def normalize_app_inventory_payload(payload: dict) -> dict:
    """Validate app_inventory.snapshot; drop icon blobs (too heavy for TX6)."""
    out = dict(payload)
    raw = out.get("apps")
    if raw is None:
        raise ValueError("apps list is required")
    if not isinstance(raw, list):
        raise ValueError("apps must be a list")
    if len(raw) > MAX_APPS:
        raise ValueError(f"apps cannot exceed {MAX_APPS} items")

    apps: list[dict] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"apps[{idx}] must be an object")
        entry = {k: v for k, v in item.items() if k not in _STRIP_APP_KEYS}

        package = entry.get("package") or entry.get("package_name")
        if not package:
            raise ValueError(f"apps[{idx}].package is required")
        entry["package"] = _clean_str(
            str(package), max_len=MAX_PACKAGE, field="package"
        )
        entry.pop("package_name", None)

        name = entry.get("name") or entry.get("app_name")
        if name is not None:
            entry["name"] = _clean_str(str(name), max_len=MAX_APP_NAME, field="name")
        else:
            entry["name"] = entry["package"]
        entry.pop("app_name", None)

        if "system" in entry and entry["system"] is not None:
            entry["system"] = _as_bool(entry["system"], field="system")
        elif "is_system" in entry and entry["is_system"] is not None:
            entry["system"] = _as_bool(entry["is_system"], field="is_system")
            entry.pop("is_system", None)
        else:
            entry["system"] = False

        version = entry.get("version") or entry.get("version_name")
        if version is not None:
            entry["version"] = _clean_str(
                str(version), max_len=MAX_VERSION, field="version"
            )
        entry.pop("version_name", None)

        apps.append(entry)

    out["apps"] = apps
    out["count"] = len(apps)
    if "include_system" in out and out["include_system"] is not None:
        out["include_system"] = _as_bool(
            out["include_system"], field="include_system"
        )
    return out


def normalize_rich_message_payload(payload: dict) -> dict:
    """Validate message.received / message.sent / message.thread shapes."""
    out = dict(payload)

    package = out.get("package") or out.get("app") or out.get("app_package")
    if package is not None:
        cleaned = _clean_str(str(package), max_len=MAX_PACKAGE, field="package")
        out["package"] = cleaned
        out["app"] = cleaned
    out.pop("app_package", None)

    thread = out.get("thread_id") or out.get("thread") or out.get("conversation_id")
    if thread is not None:
        out["thread_id"] = _clean_str(
            str(thread), max_len=MAX_THREAD_ID, field="thread_id"
        )
    out.pop("thread", None)
    out.pop("conversation_id", None)

    if out.get("contact_name") is not None:
        out["contact_name"] = _clean_str(
            str(out["contact_name"]), max_len=MAX_CONTACT_NAME, field="contact_name"
        )
    elif out.get("contact") is not None:
        out["contact_name"] = _clean_str(
            str(out["contact"]), max_len=MAX_CONTACT_NAME, field="contact"
        )
        out.pop("contact", None)

    if "title" in out and out["title"] is not None:
        out["title"] = _clean_str(str(out["title"]), max_len=MAX_TITLE, field="title")
        if "contact_name" not in out:
            out["contact_name"] = out["title"]

    direction = out.get("direction")
    if direction is not None:
        if not isinstance(direction, str):
            raise ValueError("direction must be a string")
        direction = direction.strip().lower()
        if direction not in _VALID_DIRECTIONS:
            raise ValueError(
                "direction must be one of: incoming, outgoing, unknown"
            )
        out["direction"] = direction
    else:
        out["direction"] = "unknown"

    body = out.get("body")
    if body is None:
        body = out.get("text")
    if body is not None:
        out["body"] = _clean_str(str(body), max_len=MAX_BODY, field="body")

    if "text" in out and out["text"] is not None and "body" not in out:
        out["body"] = _clean_str(str(out["text"]), max_len=MAX_BODY, field="text")

    if out.get("is_redacted") is True:
        for key in ("body", "text", "preview", "message"):
            if key in out:
                out[key] = ""

    return out


def normalize_notification_payload(payload: dict) -> dict:
    """Validate notification.* feed payloads (distinct from message.*)."""
    out = dict(payload)

    package = out.get("package") or out.get("app") or out.get("app_package")
    if package is not None:
        cleaned = _clean_str(str(package), max_len=MAX_PACKAGE, field="package")
        out["package"] = cleaned
        out["app"] = cleaned
    out.pop("app_package", None)

    if "title" in out and out["title"] is not None:
        out["title"] = _clean_str(str(out["title"]), max_len=MAX_TITLE, field="title")
    if "text" in out and out["text"] is not None:
        out["text"] = _clean_str(str(out["text"]), max_len=MAX_TEXT, field="text")
    if "channel_id" in out and out["channel_id"] is not None:
        out["channel_id"] = _clean_str(
            str(out["channel_id"]), max_len=MAX_CHANNEL, field="channel_id"
        )
    if "notification_key" in out and out["notification_key"] is not None:
        out["notification_key"] = _clean_str(
            str(out["notification_key"]), max_len=255, field="notification_key"
        )

    if "notifications" in out and out["notifications"] is not None:
        raw = out["notifications"]
        if not isinstance(raw, list):
            raise ValueError("notifications must be a list")
        if len(raw) > 200:
            raise ValueError("notifications cannot exceed 200 items")
        cleaned_list = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f"notifications[{idx}] must be an object")
            # Avoid recursive nested-list explosion: only normalize leaf fields.
            leaf = dict(item)
            leaf.pop("notifications", None)
            cleaned_list.append(normalize_notification_payload(leaf))
        out["notifications"] = cleaned_list
        out["count"] = len(cleaned_list)

    return out


def normalize_event_payload(event_type: str, payload: dict) -> dict:
    """Dispatch normalization by event type. Unknown types pass through."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    if event_type in CONTACT_SNAPSHOT_TYPES or event_type.startswith("contact."):
        return normalize_contact_snapshot_payload(payload)
    if event_type in APP_INVENTORY_TYPES or event_type.startswith("app_inventory."):
        return normalize_app_inventory_payload(payload)
    if event_type in RICH_MESSAGE_TYPES:
        return normalize_rich_message_payload(payload)
    if event_type == EventTypes.MESSAGE_NOTIFICATION:
        # Legacy path stays loosely typed; optional light cleanup only.
        return dict(payload)
    if event_type in NOTIFICATION_FEED_TYPES or event_type.startswith("notification."):
        return normalize_notification_payload(payload)
    return dict(payload)
