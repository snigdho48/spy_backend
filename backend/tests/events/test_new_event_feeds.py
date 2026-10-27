"""Contacts, app inventory, richer chat, and notification.* feeds."""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.events.infrastructure.models.event import DeviceEvent
from apps.events.infrastructure.models.snapshots import (
    DeviceAppInventorySnapshot,
    DeviceContactSnapshot,
)
from apps.events.models import DeviceAppInventorySnapshot as ReExportApp
from apps.events.models import DeviceContactSnapshot as ReExportContact


@pytest.fixture
def api_client():
    return APIClient()


def _register(api_client, email, tenant_name):
    response = api_client.post(
        reverse("auth-register"),
        {
            "email": email,
            "password": "SecurePass123!",
            "full_name": email.split("@")[0],
            "tenant_name": tenant_name,
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.data


def _auth(api_client, tokens):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")


def _pair_device(
    api_client,
    monitored_tokens,
    monitor_tokens,
    fingerprint="fp-feeds-1",
    scopes=None,
):
    _auth(api_client, monitored_tokens)
    initiate = api_client.post(
        reverse("device-pair-initiate"),
        {
            "device_name": "Feed Phone",
            "platform": "android",
            "device_fingerprint": fingerprint,
        },
        format="json",
    )
    assert initiate.status_code == status.HTTP_201_CREATED
    device_id = initiate.data["device_id"]
    code = initiate.data["pairing_code"]

    _auth(api_client, monitor_tokens)
    complete = api_client.post(
        reverse("device-pair-complete"),
        {
            "pairing_code": code.replace("-", ""),
            "consent_scopes": scopes
            or [
                "contacts",
                "app_usage",
                "messaging",
                "notifications",
                "battery",
            ],
            "consent_version": "1.0.0",
        },
        format="json",
    )
    assert complete.status_code == status.HTTP_201_CREATED, complete.data
    return device_id


@pytest.mark.django_db
class TestContactSnapshotFeed:
    def test_ingest_and_latest_read(self, api_client):
        monitored = _register(api_client, "ct-kid@example.com", "CT Kid")
        monitor = _register(api_client, "ct-par@example.com", "CT Par")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            fingerprint="fp-ct-1",
        )

        _auth(api_client, monitored["tokens"])
        ingest = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "contact.snapshot",
                        "payload": {
                            "contacts": [
                                {
                                    "name": "Dad\x00",
                                    "phones": ["+15551212"],
                                    "emails": ["dad@example.com"],
                                    "photo_base64": "iVBORw0KGgo=",
                                },
                                {
                                    "display_name": "Mom",
                                    "phone": "+15559876",
                                    "email": "mom@example.com",
                                },
                            ]
                        },
                        "idempotency_key": "contact-snap-1",
                        "timestamp": timezone.now().isoformat(),
                    }
                ],
            },
            format="json",
        )
        assert ingest.status_code == status.HTTP_202_ACCEPTED, ingest.data
        assert ingest.data["accepted"] == 1

        row = DeviceEvent.objects.get(idempotency_key="contact-snap-1")
        assert row.event_type == "contact.snapshot"
        assert row.payload["count"] == 2
        assert row.payload["contacts"][0]["name"] == "Dad"
        assert "photo_base64" not in row.payload["contacts"][0]
        assert row.payload["contacts"][1]["phones"] == ["+15559876"]

        snap = DeviceContactSnapshot.objects.get(device_id=device_id)
        assert snap.contact_count == 2
        assert ReExportContact.objects.filter(pk=snap.pk).exists()

        _auth(api_client, monitor["tokens"])
        listed = api_client.get(
            reverse("event-list"),
            {"device_id": device_id, "event_prefix": "contact"},
        )
        assert listed.status_code == status.HTTP_200_OK
        assert listed.data["count"] == 1

        latest = api_client.get(
            reverse("event-contacts-latest"),
            {"device_id": device_id},
        )
        assert latest.status_code == status.HTTP_200_OK
        assert latest.data["contact_count"] == 2
        assert latest.data["contacts"][0]["name"] == "Dad"

    def test_contacts_consent_required(self, api_client):
        monitored = _register(api_client, "ct-kid2@example.com", "CT Kid2")
        monitor = _register(api_client, "ct-par2@example.com", "CT Par2")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            fingerprint="fp-ct-noc",
            scopes=["battery"],
        )
        _auth(api_client, monitored["tokens"])
        ingest = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "contact.snapshot",
                        "payload": {"contacts": [{"name": "X", "phones": ["1"]}]},
                        "idempotency_key": "contact-noc-1",
                    }
                ],
            },
            format="json",
        )
        assert ingest.status_code == status.HTTP_202_ACCEPTED
        assert ingest.data["accepted"] == 0
        assert "contacts" in ingest.data["errors"][0]["message"]


@pytest.mark.django_db
class TestAppInventoryFeed:
    def test_ingest_strips_icons_and_latest_read(self, api_client):
        monitored = _register(api_client, "ai-kid@example.com", "AI Kid")
        monitor = _register(api_client, "ai-par@example.com", "AI Par")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            fingerprint="fp-ai-1",
        )

        _auth(api_client, monitored["tokens"])
        ingest = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "app_inventory.snapshot",
                        "payload": {
                            "include_system": False,
                            "apps": [
                                {
                                    "package": "com.whatsapp",
                                    "name": "WhatsApp",
                                    "system": False,
                                    "version": "2.24.1",
                                    "icon": "AAAA",
                                },
                                {
                                    "package_name": "com.android.settings",
                                    "app_name": "Settings",
                                    "is_system": True,
                                },
                            ],
                        },
                        "idempotency_key": "apps-snap-1",
                    }
                ],
            },
            format="json",
        )
        assert ingest.status_code == status.HTTP_202_ACCEPTED, ingest.data
        assert ingest.data["accepted"] == 1

        row = DeviceEvent.objects.get(idempotency_key="apps-snap-1")
        assert row.payload["count"] == 2
        assert "icon" not in row.payload["apps"][0]
        assert row.payload["apps"][1]["package"] == "com.android.settings"
        assert row.payload["apps"][1]["system"] is True

        snap = DeviceAppInventorySnapshot.objects.get(device_id=device_id)
        assert snap.app_count == 2
        assert snap.include_system is False
        assert ReExportApp.objects.filter(pk=snap.pk).exists()

        _auth(api_client, monitor["tokens"])
        listed = api_client.get(
            reverse("event-list"),
            {"device_id": device_id, "event_prefix": "app_inventory"},
        )
        assert listed.status_code == status.HTTP_200_OK
        assert listed.data["count"] == 1

        latest = api_client.get(
            reverse("event-app-inventory-latest"),
            {"device_id": device_id},
        )
        assert latest.status_code == status.HTTP_200_OK
        assert latest.data["app_count"] == 2
        assert latest.data["apps"][0]["package"] == "com.whatsapp"

    def test_app_inventory_maps_to_app_usage_consent(self, api_client):
        monitored = _register(api_client, "ai-kid2@example.com", "AI Kid2")
        monitor = _register(api_client, "ai-par2@example.com", "AI Par2")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            fingerprint="fp-ai-noc",
            scopes=["battery"],
        )
        _auth(api_client, monitored["tokens"])
        ingest = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "app_inventory.snapshot",
                        "payload": {
                            "apps": [{"package": "com.x", "name": "X"}],
                        },
                        "idempotency_key": "apps-noc-1",
                    }
                ],
            },
            format="json",
        )
        assert ingest.data["accepted"] == 0
        assert "app_usage" in ingest.data["errors"][0]["message"]


@pytest.mark.django_db
class TestRichChatAndNotifications:
    def test_rich_message_and_legacy_notification(self, api_client):
        monitored = _register(api_client, "msg-kid@example.com", "Msg Kid")
        monitor = _register(api_client, "msg-par@example.com", "Msg Par")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            fingerprint="fp-msg-1",
        )

        _auth(api_client, monitored["tokens"])
        ingest = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "message.notification",
                        "payload": {
                            "app": "com.whatsapp",
                            "title": "Dad",
                            "text": "Hi",
                        },
                        "idempotency_key": "msg-notif-1",
                    },
                    {
                        "event_type": "message.received",
                        "payload": {
                            "package": "com.whatsapp",
                            "thread_id": "t-dad",
                            "contact_name": "Dad",
                            "direction": "incoming",
                            "body": "On my way",
                        },
                        "idempotency_key": "msg-recv-1",
                    },
                    {
                        "event_type": "message.sent",
                        "payload": {
                            "app": "com.instagram.android",
                            "thread": "ig-1",
                            "contact": "Sam",
                            "direction": "outgoing",
                            "text": "ok",
                        },
                        "idempotency_key": "msg-sent-1",
                    },
                ],
            },
            format="json",
        )
        assert ingest.status_code == status.HTTP_202_ACCEPTED, ingest.data
        assert ingest.data["accepted"] == 3

        received = DeviceEvent.objects.get(idempotency_key="msg-recv-1")
        assert received.payload["app"] == "com.whatsapp"
        assert received.payload["direction"] == "incoming"
        assert received.payload["body"] == "On my way"

        sent = DeviceEvent.objects.get(idempotency_key="msg-sent-1")
        assert sent.payload["thread_id"] == "ig-1"
        assert sent.payload["contact_name"] == "Sam"
        assert sent.payload["body"] == "ok"

        _auth(api_client, monitor["tokens"])
        listed = api_client.get(
            reverse("event-list"),
            {"device_id": device_id, "event_prefix": "message", "page_size": 50},
        )
        assert listed.status_code == status.HTTP_200_OK
        assert listed.data["count"] == 3
        types = {r["event_type"] for r in listed.data["results"]}
        assert types == {
            "message.notification",
            "message.received",
            "message.sent",
        }

    def test_notification_feed_distinct_from_message(self, api_client):
        monitored = _register(api_client, "nt-kid@example.com", "Nt Kid")
        monitor = _register(api_client, "nt-par@example.com", "Nt Par")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            fingerprint="fp-nt-1",
        )

        _auth(api_client, monitored["tokens"])
        ingest = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "notification.posted",
                        "payload": {
                            "package": "com.google.android.gm",
                            "title": "New mail",
                            "text": "Invoice",
                            "channel_id": "mail",
                        },
                        "idempotency_key": "notif-1",
                    },
                    {
                        "event_type": "message.notification",
                        "payload": {
                            "app": "com.whatsapp",
                            "title": "Dad",
                            "text": "Hi",
                        },
                        "idempotency_key": "notif-msg-1",
                    },
                ],
            },
            format="json",
        )
        assert ingest.data["accepted"] == 2

        _auth(api_client, monitor["tokens"])
        notifs = api_client.get(
            reverse("event-list"),
            {"device_id": device_id, "event_prefix": "notification"},
        )
        assert notifs.status_code == status.HTTP_200_OK
        assert notifs.data["count"] == 1
        assert notifs.data["results"][0]["event_type"] == "notification.posted"

        msgs = api_client.get(
            reverse("event-list"),
            {"device_id": device_id, "event_prefix": "message"},
        )
        assert msgs.data["count"] == 1
        assert msgs.data["results"][0]["event_type"] == "message.notification"

    def test_messaging_consent_gates_rich_chat(self, api_client):
        monitored = _register(api_client, "msg-kid2@example.com", "Msg Kid2")
        monitor = _register(api_client, "msg-par2@example.com", "Msg Par2")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            fingerprint="fp-msg-noc",
            scopes=["notifications"],
        )
        _auth(api_client, monitored["tokens"])
        ingest = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "message.received",
                        "payload": {
                            "package": "com.whatsapp",
                            "body": "x",
                            "direction": "incoming",
                        },
                        "idempotency_key": "msg-noc-1",
                    },
                    {
                        "event_type": "notification.posted",
                        "payload": {
                            "package": "com.android.systemui",
                            "title": "Battery",
                        },
                        "idempotency_key": "nt-ok-1",
                    },
                ],
            },
            format="json",
        )
        assert ingest.data["accepted"] == 1
        assert ingest.data["rejected"] == 1
        assert "messaging" in ingest.data["errors"][0]["message"]
