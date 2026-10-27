import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.infrastructure.models.audit_log import AuditLog
from apps.devices.infrastructure.models.screen_share import ScreenShareSession
from apps.tenants.infrastructure.models.membership import TenantMembership


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


def _pair_device(api_client, monitored_tokens, monitor_tokens, scopes, fingerprint):
    _auth(api_client, monitored_tokens)
    initiate = api_client.post(
        reverse("device-pair-initiate"),
        {
            "device_name": "Screen Phone",
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
            "consent_scopes": scopes,
            "consent_version": "1.0.0",
        },
        format="json",
    )
    assert complete.status_code == status.HTTP_201_CREATED
    return device_id


@pytest.mark.django_db
class TestScreenShare:
    def test_full_session_lifecycle(self, api_client):
        monitored = _register(api_client, "scr-kid@example.com", "Kid Scr")
        monitor = _register(api_client, "scr-parent@example.com", "Parent Scr")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            ["location", "screen"],
            "fp-scr-1",
        )

        # Monitor requests a session.
        _auth(api_client, monitor["tokens"])
        req = api_client.post(
            reverse("device-screen-request", kwargs={"device_id": device_id}),
            format="json",
        )
        assert req.status_code == status.HTTP_201_CREATED
        assert req.data["status"] == "requested"
        assert req.data["ws_url"].startswith("ws/v1/screen/")
        session_id = req.data["id"]

        # Monitored device sees the pending request.
        _auth(api_client, monitored["tokens"])
        pending = api_client.get(
            reverse("device-screen-pending", kwargs={"device_id": device_id})
        )
        assert pending.status_code == status.HTTP_200_OK
        assert len(pending.data["results"]) == 1

        # Monitored device starts streaming.
        start = api_client.post(
            reverse("device-screen-start", kwargs={"session_id": session_id}),
            format="json",
        )
        assert start.status_code == status.HTTP_200_OK
        assert start.data["status"] == "active"
        assert start.data["started_at"] is not None

        # Monitor ends the session.
        _auth(api_client, monitor["tokens"])
        end = api_client.post(
            reverse("device-screen-end", kwargs={"session_id": session_id}),
            {"reason": "done watching"},
            format="json",
        )
        assert end.status_code == status.HTTP_200_OK
        assert end.data["status"] == "ended"

        assert ScreenShareSession.objects.get(pk=session_id).status == "ended"
        actions = set(
            AuditLog.objects.filter(resource_id=device_id).values_list(
                "action", flat=True
            )
        )
        assert "screen_share.requested" in actions
        assert "screen_share.started" in actions
        assert "screen_share.ended" in actions

    def test_request_requires_screen_consent(self, api_client):
        monitored = _register(api_client, "scr-kid2@example.com", "Kid Scr2")
        monitor = _register(api_client, "scr-parent2@example.com", "Parent Scr2")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            ["location", "battery"],
            "fp-scr-2",
        )

        _auth(api_client, monitor["tokens"])
        req = api_client.post(
            reverse("device-screen-request", kwargs={"device_id": device_id}),
            format="json",
        )
        assert req.status_code == status.HTTP_403_FORBIDDEN
        assert req.data["error"]["code"] == "consent_required"

    def test_pause_blocks_request(self, api_client):
        monitored = _register(api_client, "scr-kid3@example.com", "Kid Scr3")
        monitor = _register(api_client, "scr-parent3@example.com", "Parent Scr3")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            ["screen"],
            "fp-scr-3",
        )

        _auth(api_client, monitored["tokens"])
        pause = api_client.post(
            reverse("device-owned-pause", kwargs={"device_id": device_id}),
            {"duration_minutes": 30},
            format="json",
        )
        assert pause.status_code == status.HTTP_200_OK

        _auth(api_client, monitor["tokens"])
        req = api_client.post(
            reverse("device-screen-request", kwargs={"device_id": device_id}),
            format="json",
        )
        assert req.status_code == status.HTTP_409_CONFLICT

    def test_viewer_cannot_request(self, api_client):
        monitored = _register(api_client, "scr-kid4@example.com", "Kid Scr4")
        monitor = _register(api_client, "scr-parent4@example.com", "Parent Scr4")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            ["screen"],
            "fp-scr-4",
        )

        membership = TenantMembership.objects.get(user__email="scr-parent4@example.com")
        membership.role = TenantMembership.Role.VIEWER
        membership.save(update_fields=["role"])

        _auth(api_client, monitor["tokens"])
        req = api_client.post(
            reverse("device-screen-request", kwargs={"device_id": device_id}),
            format="json",
        )
        assert req.status_code == status.HTTP_403_FORBIDDEN
        assert req.data["error"]["code"] == "forbidden"

    def test_start_requires_screen_consent_after_revoke(self, api_client):
        monitored = _register(api_client, "scr-kid5@example.com", "Kid Scr5")
        monitor = _register(api_client, "scr-parent5@example.com", "Parent Scr5")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            ["screen"],
            "fp-scr-5",
        )

        _auth(api_client, monitor["tokens"])
        req = api_client.post(
            reverse("device-screen-request", kwargs={"device_id": device_id}),
            format="json",
        )
        assert req.status_code == status.HTTP_201_CREATED
        session_id = req.data["id"]

        # Revoke the screen consent by replacing it with a scopeless record.
        from apps.devices.infrastructure.models.device import ConsentRecord, Device
        from django.utils import timezone

        device = Device.objects.get(pk=device_id)
        ConsentRecord.objects.filter(device=device, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        ConsentRecord.objects.create(
            tenant=device.tenant,
            device=device,
            granted_by=device.owner,
            scopes=["location"],
            consent_version="1.0.0",
        )

        _auth(api_client, monitored["tokens"])
        start = api_client.post(
            reverse("device-screen-start", kwargs={"session_id": session_id}),
            format="json",
        )
        assert start.status_code == status.HTTP_403_FORBIDDEN
        assert start.data["error"]["code"] == "consent_required"

    def test_deny_session(self, api_client):
        monitored = _register(api_client, "scr-kid6@example.com", "Kid Scr6")
        monitor = _register(api_client, "scr-parent6@example.com", "Parent Scr6")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            ["screen"],
            "fp-scr-6",
        )

        _auth(api_client, monitor["tokens"])
        req = api_client.post(
            reverse("device-screen-request", kwargs={"device_id": device_id}),
            format="json",
        )
        session_id = req.data["id"]

        _auth(api_client, monitored["tokens"])
        deny = api_client.post(
            reverse("device-screen-deny", kwargs={"session_id": session_id}),
            {"reason": "not now"},
            format="json",
        )
        assert deny.status_code == status.HTTP_200_OK
        assert deny.data["status"] == "denied"
        assert AuditLog.objects.filter(
            resource_id=device_id, action="screen_share.denied"
        ).exists()


# ---------------------------------------------------------------------------
# Extra coverage: reuse HTTP status, lazy TTL expire, mid-session WS kick.
# ---------------------------------------------------------------------------

import asyncio
import json
from datetime import timedelta
from urllib.parse import quote

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.devices.application.services.screen_share_service import (
    REQUEST_TTL,
    ScreenShareService,
)
from apps.devices.infrastructure.models.device import ConsentRecord, Device
from config.asgi import application

User = get_user_model()


def _ws_path(session_id, token):
    return f"/ws/v1/screen/{session_id}/?token={quote(token)}"


@pytest.mark.django_db
class TestScreenShareExtras:
    def test_request_reuse_returns_200(self, api_client):
        monitored = _register(api_client, "scr-reuse-kid@example.com", "Kid Reuse")
        monitor = _register(api_client, "scr-reuse-parent@example.com", "Parent Reuse")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            ["screen"],
            "fp-scr-reuse",
        )

        _auth(api_client, monitor["tokens"])
        first = api_client.post(
            reverse("device-screen-request", kwargs={"device_id": device_id}),
            format="json",
        )
        assert first.status_code == status.HTTP_201_CREATED
        session_id = first.data["id"]

        second = api_client.post(
            reverse("device-screen-request", kwargs={"device_id": device_id}),
            format="json",
        )
        assert second.status_code == status.HTTP_200_OK
        assert second.data["id"] == session_id

    def test_stale_requested_expires_on_pending(self, api_client):
        monitored = _register(api_client, "scr-exp-kid@example.com", "Kid Exp")
        monitor = _register(api_client, "scr-exp-parent@example.com", "Parent Exp")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            ["screen"],
            "fp-scr-exp",
        )

        _auth(api_client, monitor["tokens"])
        req = api_client.post(
            reverse("device-screen-request", kwargs={"device_id": device_id}),
            format="json",
        )
        assert req.status_code == status.HTTP_201_CREATED
        session_id = req.data["id"]

        session = ScreenShareSession.objects.get(pk=session_id)
        session.requested_at = timezone.now() - REQUEST_TTL - timedelta(seconds=5)
        session.save(update_fields=["requested_at"])

        _auth(api_client, monitored["tokens"])
        pending = api_client.get(
            reverse("device-screen-pending", kwargs={"device_id": device_id})
        )
        assert pending.status_code == status.HTTP_200_OK
        assert pending.data["results"] == []
        session.refresh_from_db()
        assert session.status == ScreenShareSession.Status.EXPIRED
        assert AuditLog.objects.filter(
            resource_id=device_id, action="screen_share.expired"
        ).exists()


@pytest.mark.django_db(transaction=True)
class TestScreenShareConsumer:
    def _setup_active_session(self, api_client, kid_email, parent_email, fp):
        monitored = _register(api_client, kid_email, "Kid WS")
        monitor = _register(api_client, parent_email, "Parent WS")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            ["screen"],
            fp,
        )
        _auth(api_client, monitor["tokens"])
        req = api_client.post(
            reverse("device-screen-request", kwargs={"device_id": device_id}),
            format="json",
        )
        assert req.status_code == status.HTTP_201_CREATED
        session_id = req.data["id"]
        _auth(api_client, monitored["tokens"])
        start = api_client.post(
            reverse("device-screen-start", kwargs={"session_id": session_id}),
            format="json",
        )
        assert start.status_code == status.HTTP_200_OK
        return monitored, monitor, device_id, session_id

    def test_end_mid_session_closes_stream(self, api_client):
        monitored, monitor, _device_id, session_id = self._setup_active_session(
            api_client,
            "scr-ws-end-kid@example.com",
            "scr-ws-end-parent@example.com",
            "fp-scr-ws-end",
        )
        token = monitored["tokens"]["access"]
        parent_email = "scr-ws-end-parent@example.com"

        async def _run():
            communicator = WebsocketCommunicator(
                application, _ws_path(session_id, token)
            )
            connected, _ = await communicator.connect()
            assert connected is True
            ready = json.loads(await communicator.receive_from())
            assert ready["type"] == "screen.ready"
            assert ready["role"] == "publisher"

            parent = await sync_to_async(User.objects.get)(email=parent_email)
            await sync_to_async(ScreenShareService().end_session)(
                user=parent, session_id=session_id, reason="done"
            )

            closed = json.loads(await communicator.receive_from())
            assert closed["type"] == "screen.closed"
            # Close frame from consumer; ignore further.
            try:
                await communicator.receive_output(timeout=1)
            except Exception:
                pass
            await communicator.disconnect()

        asyncio.run(_run())
        assert ScreenShareSession.objects.get(pk=session_id).status == "ended"

    def test_revoke_mid_session_closes_stream(self, api_client):
        monitored, _monitor, device_id, session_id = self._setup_active_session(
            api_client,
            "scr-ws-rev-kid@example.com",
            "scr-ws-rev-parent@example.com",
            "fp-scr-ws-rev",
        )
        token = monitored["tokens"]["access"]

        async def _run():
            communicator = WebsocketCommunicator(
                application, _ws_path(session_id, token)
            )
            connected, _ = await communicator.connect()
            assert connected is True
            ready = json.loads(await communicator.receive_from())
            assert ready["type"] == "screen.ready"

            def _revoke():
                device = Device.objects.get(pk=device_id)
                ConsentRecord.objects.filter(
                    device=device, revoked_at__isnull=True
                ).update(revoked_at=timezone.now())
                ConsentRecord.objects.create(
                    tenant=device.tenant,
                    device=device,
                    granted_by=device.owner,
                    scopes=["location"],
                    consent_version="1.0.0",
                )
                ScreenShareService().terminate_open_for_device(
                    device, reason="consent_revoked"
                )

            await sync_to_async(_revoke)()

            closed = json.loads(await communicator.receive_from())
            assert closed["type"] == "screen.closed"
            assert closed["reason"] == "consent_revoked"
            try:
                await communicator.receive_output(timeout=1)
            except Exception:
                pass
            await communicator.disconnect()

        asyncio.run(_run())
        assert ScreenShareSession.objects.get(pk=session_id).status == "ended"
