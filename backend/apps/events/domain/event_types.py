"""Canonical event type / prefix constants for collectors and monitors.

Prefixes map to consent scopes in ConsentService.validate_event_scope.
Existing collectors that already emit these types must keep working:
message.notification, app_usage.snapshot, etc.
"""

from __future__ import annotations


class EventPrefixes:
    CONTACT = "contact"
    APP_INVENTORY = "app_inventory"
    MESSAGE = "message"
    NOTIFICATION = "notification"
    APP_USAGE = "app_usage"
    CALL = "call"
    SMS = "sms"
    LOCATION = "location"
    GEOFENCE = "geofence"
    BATTERY = "battery"
    NETWORK = "network"
    DEVICE_INFO = "device_info"
    SIM = "sim"


class EventTypes:
    # Address-book contacts (full snapshot)
    CONTACT_SNAPSHOT = "contact.snapshot"
    CONTACT_UPDATE = "contact.update"

    # Remote installed-app inventory (distinct from app_usage.*)
    APP_INVENTORY_SNAPSHOT = "app_inventory.snapshot"

    # Messaging / chat (richer than notification-only)
    MESSAGE_NOTIFICATION = "message.notification"  # legacy notification preview
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_SENT = "message.sent"
    MESSAGE_THREAD = "message.thread"

    # General notifications feed (not chat)
    NOTIFICATION_POSTED = "notification.posted"
    NOTIFICATION_REMOVED = "notification.removed"
    NOTIFICATION_SNAPSHOT = "notification.snapshot"

    # Existing collectors (documented for completeness)
    APP_USAGE_SNAPSHOT = "app_usage.snapshot"
    LOCATION_UPDATE = "location.update"
    LOCATION_SNAPSHOT = "location.snapshot"
    CALL_LOG = "call.log"
    SMS_RECEIVED = "sms.received"


# Prefixes that carry call/sms contact *metadata* (not address-book snapshots).
CALL_SMS_CONTACT_PREFIXES = ("call.", "sms.")

RICH_MESSAGE_TYPES = frozenset(
    {
        EventTypes.MESSAGE_RECEIVED,
        EventTypes.MESSAGE_SENT,
        EventTypes.MESSAGE_THREAD,
    }
)

CONTACT_SNAPSHOT_TYPES = frozenset(
    {
        EventTypes.CONTACT_SNAPSHOT,
        EventTypes.CONTACT_UPDATE,
    }
)

APP_INVENTORY_TYPES = frozenset(
    {
        EventTypes.APP_INVENTORY_SNAPSHOT,
    }
)

NOTIFICATION_FEED_TYPES = frozenset(
    {
        EventTypes.NOTIFICATION_POSTED,
        EventTypes.NOTIFICATION_REMOVED,
        EventTypes.NOTIFICATION_SNAPSHOT,
    }
)
