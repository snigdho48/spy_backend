import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.infrastructure.models.audit_log import AuditLog
from apps.devices.infrastructure.models.device import ConsentRecord, Device, SharingPause
from apps.events.infrastructure.models.event import DeviceEvent


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


def _pair_device(api_client, monitored_tokens, monitor_tokens, fingerprint="fp-pause-1"):
    _auth(api_client, monitored_tokens)
    initiate = api_client.post(
        reverse("device-pair-initiate"),
        {
            "device_name": "Pause Phone",
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
            "consent_scopes": ["location", "battery", "sms"],
            "consent_version": "1.0.0",
        },
        format="json",
    )
    assert complete.status_code == status.HTTP_201_CREATED
    return device_id


@pytest.mark.django_db
class TestSharingPause:
    def test_owner_can_pause_and_resume(self, api_client):
        monitored = _register(api_client, "pause-kid@example.com", "Kid Pause")
        monitor = _register(api_client, "pause-parent@example.com", "Parent Pause")
        device_id = _pair_device(api_client, monitored["tokens"], monitor["tokens"])

        _auth(api_client, monitored["tokens"])
        pause = api_client.post(
            reverse("device-owned-pause", kwargs={"device_id": device_id}),
            {"duration_minutes": 60, "reason": "school quiet hours"},
            format="json",
        )
        assert pause.status_code == status.HTTP_200_OK
        assert pause.data["sharing"]["paused"] is True
        assert pause.data["sharing"]["paused_until"] is not None
        assert pause.data["sharing"]["resumes_in_s"] > 0

        device = Device.objects.get(pk=device_id)
        assert device.is_paused is True
        assert ConsentRecord.objects.filter(device=device, revoked_at__isnull=True).exists()

        status_resp = api_client.get(
            reverse("device-owned-status", kwargs={"device_id": device_id})
        )
        assert status_resp.status_code == status.HTTP_200_OK
        assert status_resp.data["sharing"]["paused"] is True

        resume = api_client.post(
            reverse("device-owned-resume", kwargs={"device_id": device_id}),
            format="json",
        )
        assert resume.status_code == status.HTTP_200_OK
        assert resume.data["sharing"]["paused"] is False
        assert Device.objects.get(pk=device_id).is_paused is False

        actions = set(
            AuditLog.objects.filter(resource_id=device_id).values_list(
                "action", flat=True
            )
        )
        assert "device.sharing_paused" in actions
        assert "device.sharing_resumed" in actions

    def test_monitor_cannot_pause(self, api_client):
        monitored = _register(api_client, "pause-kid2@example.com", "Kid Pause 2")
        monitor = _register(api_client, "pause-parent2@example.com", "Parent Pause 2")
        device_id = _pair_device(
            api_client, monitored["tokens"], monitor["tokens"], fingerprint="fp-pause-2"
        )

        _auth(api_client, monitor["tokens"])
        pause = api_client.post(
            reverse("device-owned-pause", kwargs={"device_id": device_id}),
            {"duration_minutes": 30},
            format="json",
        )
        assert pause.status_code == status.HTTP_404_NOT_FOUND

        detail = api_client.get(reverse("device-detail", kwargs={"device_id": device_id}))
        assert detail.status_code == status.HTTP_200_OK
        assert detail.data["sharing"]["paused"] is False

    def test_ingest_rejects_while_paused(self, api_client):
        monitored = _register(api_client, "pause-kid3@example.com", "Kid Pause 3")
        monitor = _register(api_client, "pause-parent3@example.com", "Parent Pause 3")
        device_id = _pair_device(
            api_client, monitored["tokens"], monitor["tokens"], fingerprint="fp-pause-3"
        )

        _auth(api_client, monitored["tokens"])
        pause = api_client.post(
            reverse("device-owned-pause", kwargs={"device_id": device_id}),
            {"duration_minutes": 15},
            format="json",
        )
        assert pause.status_code == status.HTTP_200_OK
        paused_until = pause.data["sharing"]["paused_until"]

        ingest = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "battery.status",
                        "payload": {"level": 50},
                        "idempotency_key": "bat-paused-1",
                        "timestamp": timezone.now().isoformat(),
                    }
                ],
            },
            format="json",
        )
        assert ingest.status_code == status.HTTP_202_ACCEPTED
        assert ingest.data["accepted"] == 0
        assert ingest.data["paused"] is True
        assert ingest.data["paused_until"] is not None
        assert DeviceEvent.objects.filter(device_id=device_id).count() == 0

        # Consent untouched
        assert ConsentRecord.objects.filter(
            device_id=device_id, revoked_at__isnull=True
        ).exists()
        assert paused_until

    def test_ingest_drops_events_in_pause_window_after_resume(self, api_client):
        monitored = _register(api_client, "pause-kid4@example.com", "Kid Pause 4")
        monitor = _register(api_client, "pause-parent4@example.com", "Parent Pause 4")
        device_id = _pair_device(
            api_client, monitored["tokens"], monitor["tokens"], fingerprint="fp-pause-4"
        )

        _auth(api_client, monitored["tokens"])
        api_client.post(
            reverse("device-owned-pause", kwargs={"device_id": device_id}),
            {"duration_minutes": 60},
            format="json",
        )
        pause_row = SharingPause.objects.get(device_id=device_id, ended_at__isnull=True)
        # Backdate the pause so a mid-window timestamp is before resume.
        pause_row.started_at = timezone.now() - timezone.timedelta(minutes=10)
        pause_row.save(update_fields=["started_at", "updated_at"])
        mid_pause = pause_row.started_at + timezone.timedelta(minutes=5)

        api_client.post(
            reverse("device-owned-resume", kwargs={"device_id": device_id}),
            format="json",
        )

        after = timezone.now()
        ingest = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "battery.status",
                        "payload": {"level": 40},
                        "idempotency_key": "bat-during-pause",
                        "timestamp": mid_pause.isoformat(),
                    },
                    {
                        "event_type": "battery.status",
                        "payload": {"level": 41},
                        "idempotency_key": "bat-after-resume",
                        "timestamp": after.isoformat(),
                    },
                ],
            },
            format="json",
        )
        assert ingest.status_code == status.HTTP_202_ACCEPTED
        assert ingest.data["accepted"] == 1
        assert ingest.data["rejected"] == 1
        keys = set(
            DeviceEvent.objects.filter(device_id=device_id).values_list(
                "idempotency_key", flat=True
            )
        )
        assert "bat-after-resume" in keys
        assert "bat-during-pause" not in keys

    def test_invalid_duration_rejected(self, api_client):
        monitored = _register(api_client, "pause-kid5@example.com", "Kid Pause 5")
        monitor = _register(api_client, "pause-parent5@example.com", "Parent Pause 5")
        device_id = _pair_device(
            api_client, monitored["tokens"], monitor["tokens"], fingerprint="fp-pause-5"
        )

        _auth(api_client, monitored["tokens"])
        pause = api_client.post(
            reverse("device-owned-pause", kwargs={"device_id": device_id}),
            {"duration_minutes": 45},
            format="json",
        )
        assert pause.status_code == status.HTTP_400_BAD_REQUEST

    def test_pause_expired_lazy(self, api_client):
        monitored = _register(api_client, "pause-kid6@example.com", "Kid Pause 6")
        monitor = _register(api_client, "pause-parent6@example.com", "Parent Pause 6")
        device_id = _pair_device(
            api_client, monitored["tokens"], monitor["tokens"], fingerprint="fp-pause-6"
        )

        _auth(api_client, monitored["tokens"])
        api_client.post(
            reverse("device-owned-pause", kwargs={"device_id": device_id}),
            {"duration_minutes": 15},
            format="json",
        )
        pause = SharingPause.objects.get(device_id=device_id, ended_at__isnull=True)
        pause.expires_at = timezone.now() - timezone.timedelta(seconds=5)
        pause.save(update_fields=["expires_at", "updated_at"])

        status_resp = api_client.get(
            reverse("device-owned-status", kwargs={"device_id": device_id})
        )
        assert status_resp.status_code == status.HTTP_200_OK
        assert status_resp.data["sharing"]["paused"] is False
        pause.refresh_from_db()
        assert pause.ended_at is not None
        assert AuditLog.objects.filter(
            resource_id=device_id, action="device.sharing_pause_expired"
        ).exists()
