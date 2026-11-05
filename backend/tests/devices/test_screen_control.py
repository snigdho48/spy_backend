import asyncio
import json
from datetime import timedelta
from urllib.parse import quote

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.infrastructure.models.audit_log import AuditLog
from apps.devices.application.services.screen_control import validate_control_intent
from apps.devices.application.services.screen_share_service import (
    CONTROL_REQUEST_TTL,
    ScreenShareService,
)
from apps.devices.infrastructure.models.screen_share import ScreenShareSession
from config.asgi import application
from tests.devices.test_screen_share import _auth, _pair_device, _register


@pytest.fixture
def api_client():
    return APIClient()


def _ws_path(session_id, token):
    return f"/ws/v1/screen/{session_id}/?token={quote(token)}"


def _open_session(api_client, kid_email, parent_email, fp, scopes=None):
    monitored = _register(api_client, kid_email, "Kid Ctrl")
    monitor = _register(api_client, parent_email, "Parent Ctrl")
    device_id = _pair_device(
        api_client,
        monitored["tokens"],
        monitor["tokens"],
        scopes or ["screen"],
        fp,
    )
    _auth(api_client, monitor["tokens"])
    req = api_client.post(
        reverse("device-screen-request", kwargs={"device_id": device_id}),
        format="json",
    )
    assert req.status_code == status.HTTP_201_CREATED
    session_id = req.data["id"]
    assert req.data["control_status"] == "none"
    _auth(api_client, monitored["tokens"])
    start = api_client.post(
        reverse("device-screen-start", kwargs={"session_id": session_id}),
        format="json",
    )
    assert start.status_code == status.HTTP_200_OK
    return monitored, monitor, device_id, session_id


class TestValidateControlIntent:
    def test_accepts_supported_gestures(self):
        assert validate_control_intent({"action": "tap", "x": 0.25, "y": 0.75}) == {
            "action": "tap",
            "x": 0.25,
            "y": 0.75,
            "duration_ms": 50,
        }
        assert validate_control_intent(
            {"action": "swipe", "x": 0.1, "y": 0.2, "x2": 0.8, "y2": 0.9, "duration_ms": 400}
        )["action"] == "swipe"
        assert validate_control_intent({"action": "back"}) == {"action": "back"}
        assert validate_control_intent({"action": "home"}) == {"action": "home"}
        assert validate_control_intent({"action": "recents"}) == {"action": "recents"}

    def test_rejects_unknown_or_out_of_range(self):
        assert validate_control_intent({"action": "keylog"}) is None
        assert validate_control_intent({"action": "type_text", "text": "secret"}) is None
        assert validate_control_intent({"action": "tap", "x": 1.5, "y": 0.2}) is None
        assert validate_control_intent({"action": "tap", "x": -0.1, "y": 0.2}) is None
        assert validate_control_intent(None) is None
        assert validate_control_intent({"action": "swipe", "x": 0.1, "y": 0.2}) is None


@pytest.mark.django_db
class TestScreenControlGrant:
    def test_request_approve_end_lifecycle(self, api_client):
        monitored, monitor, device_id, session_id = _open_session(
            api_client,
            "ctrl-kid@example.com",
            "ctrl-parent@example.com",
            "fp-ctrl-1",
        )

        _auth(api_client, monitor["tokens"])
        req = api_client.post(
            reverse("device-screen-control-request", kwargs={"session_id": session_id}),
            format="json",
        )
        assert req.status_code == status.HTTP_201_CREATED
        assert req.data["control_status"] == "requested"
        assert req.data["control_requested_at"] is not None
        assert req.data["status"] == "active"

        # Idempotent re-request while pending.
        again = api_client.post(
            reverse("device-screen-control-request", kwargs={"session_id": session_id}),
            format="json",
        )
        assert again.status_code == status.HTTP_200_OK
        assert again.data["control_status"] == "requested"

        _auth(api_client, monitored["tokens"])
        approve = api_client.post(
            reverse("device-screen-control-approve", kwargs={"session_id": session_id}),
            format="json",
        )
        assert approve.status_code == status.HTTP_200_OK
        assert approve.data["control_status"] == "approved"
        assert approve.data["control_started_at"] is not None

        # Approve is idempotent once granted.
        approve_again = api_client.post(
            reverse("device-screen-control-approve", kwargs={"session_id": session_id}),
            format="json",
        )
        assert approve_again.status_code == status.HTTP_200_OK
        assert approve_again.data["control_status"] == "approved"

        _auth(api_client, monitor["tokens"])
        end = api_client.post(
            reverse("device-screen-control-end", kwargs={"session_id": session_id}),
            {"reason": "done controlling"},
            format="json",
        )
        assert end.status_code == status.HTTP_200_OK
        assert end.data["control_status"] == "none"
        assert end.data["status"] == "active"

        actions = set(
            AuditLog.objects.filter(resource_id=device_id).values_list("action", flat=True)
        )
        assert "screen_share.control_requested" in actions
        assert "screen_share.control_approved" in actions
        assert "screen_share.control_ended" in actions

    def test_deny_blocks_and_can_be_requested_again(self, api_client):
        monitored, monitor, device_id, session_id = _open_session(
            api_client,
            "ctrl-kid2@example.com",
            "ctrl-parent2@example.com",
            "fp-ctrl-2",
        )

        _auth(api_client, monitor["tokens"])
        req = api_client.post(
            reverse("device-screen-control-request", kwargs={"session_id": session_id}),
            format="json",
        )
        assert req.status_code == status.HTTP_201_CREATED

        _auth(api_client, monitored["tokens"])
        deny = api_client.post(
            reverse("device-screen-control-deny", kwargs={"session_id": session_id}),
            {"reason": "not now"},
            format="json",
        )
        assert deny.status_code == status.HTTP_200_OK
        assert deny.data["control_status"] == "denied"
        assert deny.data["status"] == "active"

        # Approve after deny is rejected — no pending request.
        approve = api_client.post(
            reverse("device-screen-control-approve", kwargs={"session_id": session_id}),
            format="json",
        )
        assert approve.status_code == status.HTTP_409_CONFLICT

        _auth(api_client, monitor["tokens"])
        again = api_client.post(
            reverse("device-screen-control-request", kwargs={"session_id": session_id}),
            format="json",
        )
        assert again.status_code == status.HTTP_201_CREATED
        assert again.data["control_status"] == "requested"

        assert AuditLog.objects.filter(
            resource_id=device_id, action="screen_share.control_denied"
        ).exists()

    def test_approve_without_request_conflicts(self, api_client):
        monitored, _monitor, _device_id, session_id = _open_session(
            api_client,
            "ctrl-kid3@example.com",
            "ctrl-parent3@example.com",
            "fp-ctrl-3",
        )
        _auth(api_client, monitored["tokens"])
        approve = api_client.post(
            reverse("device-screen-control-approve", kwargs={"session_id": session_id}),
            format="json",
        )
        assert approve.status_code == status.HTTP_409_CONFLICT

    def test_device_cannot_request_control(self, api_client):
        monitored, _monitor, _device_id, session_id = _open_session(
            api_client,
            "ctrl-kid4@example.com",
            "ctrl-parent4@example.com",
            "fp-ctrl-4",
        )
        _auth(api_client, monitored["tokens"])
        req = api_client.post(
            reverse("device-screen-control-request", kwargs={"session_id": session_id}),
            format="json",
        )
        assert req.status_code == status.HTTP_403_FORBIDDEN

    def test_monitor_cannot_approve(self, api_client):
        _monitored, monitor, _device_id, session_id = _open_session(
            api_client,
            "ctrl-kid5@example.com",
            "ctrl-parent5@example.com",
            "fp-ctrl-5",
        )
        _auth(api_client, monitor["tokens"])
        api_client.post(
            reverse("device-screen-control-request", kwargs={"session_id": session_id}),
            format="json",
        )
        approve = api_client.post(
            reverse("device-screen-control-approve", kwargs={"session_id": session_id}),
            format="json",
        )
        assert approve.status_code == status.HTTP_404_NOT_FOUND

    def test_ending_view_session_clears_control(self, api_client):
        monitored, monitor, _device_id, session_id = _open_session(
            api_client,
            "ctrl-kid6@example.com",
            "ctrl-parent6@example.com",
            "fp-ctrl-6",
        )
        _auth(api_client, monitor["tokens"])
        api_client.post(
            reverse("device-screen-control-request", kwargs={"session_id": session_id}),
            format="json",
        )
        _auth(api_client, monitored["tokens"])
        api_client.post(
            reverse("device-screen-control-approve", kwargs={"session_id": session_id}),
            format="json",
        )
        _auth(api_client, monitor["tokens"])
        end = api_client.post(
            reverse("device-screen-end", kwargs={"session_id": session_id}),
            {"reason": "done watching"},
            format="json",
        )
        assert end.status_code == status.HTTP_200_OK
        session = ScreenShareSession.objects.get(pk=session_id)
        assert session.status == "ended"
        assert session.control_status == "none"

    def test_stale_control_request_expires(self, api_client):
        _monitored, monitor, _device_id, session_id = _open_session(
            api_client,
            "ctrl-kid7@example.com",
            "ctrl-parent7@example.com",
            "fp-ctrl-7",
        )
        _auth(api_client, monitor["tokens"])
        req = api_client.post(
            reverse("device-screen-control-request", kwargs={"session_id": session_id}),
            format="json",
        )
        assert req.data["control_status"] == "requested"

        session = ScreenShareSession.objects.get(pk=session_id)
        session.control_requested_at = (
            timezone.now() - CONTROL_REQUEST_TTL - timedelta(seconds=5)
        )
        session.save(update_fields=["control_requested_at"])

        status_resp = api_client.get(
            reverse("device-screen-status", kwargs={"session_id": session_id})
        )
        assert status_resp.status_code == status.HTTP_200_OK
        assert status_resp.data["control_status"] == "none"
        session.refresh_from_db()
        assert session.control_ended_reason == "expired"


@pytest.mark.django_db(transaction=True)
class TestScreenControlConsumer:
    def test_control_blocked_until_approved_then_relayed(self, api_client):
        monitored, monitor, _device_id, session_id = _open_session(
            api_client,
            "ctrl-ws-kid@example.com",
            "ctrl-ws-parent@example.com",
            "fp-ctrl-ws",
        )
        kid_token = monitored["tokens"]["access"]
        parent_token = monitor["tokens"]["access"]
        kid_email = "ctrl-ws-kid@example.com"
        parent_email = "ctrl-ws-parent@example.com"

        async def _run():
            publisher = WebsocketCommunicator(
                application, _ws_path(session_id, kid_token)
            )
            viewer = WebsocketCommunicator(
                application, _ws_path(session_id, parent_token)
            )
            connected, _ = await publisher.connect()
            assert connected is True
            connected, _ = await viewer.connect()
            assert connected is True

            pub_ready = json.loads(await publisher.receive_from())
            view_ready = json.loads(await viewer.receive_from())
            assert pub_ready["role"] == "publisher"
            assert view_ready["role"] == "viewer"

            await viewer.send_to(
                text_data=json.dumps(
                    {"type": "screen.control", "data": {"action": "tap", "x": 0.5, "y": 0.5}}
                )
            )
            nack = json.loads(await viewer.receive_from())
            assert nack["type"] == "screen.control_nack"
            assert nack["reason"] == "not_approved"

            from django.contrib.auth import get_user_model

            User = get_user_model()
            parent = await sync_to_async(User.objects.get)(email=parent_email)
            kid = await sync_to_async(User.objects.get)(email=kid_email)
            await sync_to_async(ScreenShareService().request_control)(
                user=parent, session_id=session_id
            )

            # Both sockets get the control_requested signal.
            pub_signal = json.loads(await publisher.receive_from())
            view_signal = json.loads(await viewer.receive_from())
            assert pub_signal["type"] == "screen.signal"
            assert pub_signal["data"]["signal"] == "control_requested"
            assert view_signal["data"]["signal"] == "control_requested"

            await sync_to_async(ScreenShareService().approve_control)(
                user=kid, session_id=session_id
            )
            pub_approved = json.loads(await publisher.receive_from())
            view_approved = json.loads(await viewer.receive_from())
            assert pub_approved["data"]["signal"] == "control_approved"
            assert view_approved["data"]["signal"] == "control_approved"

            await viewer.send_to(
                text_data=json.dumps(
                    {
                        "type": "screen.control",
                        "data": {"action": "tap", "x": 0.4, "y": 0.6, "seq": 7},
                    }
                )
            )
            relayed = json.loads(await publisher.receive_from())
            assert relayed["type"] == "screen.control"
            assert relayed["data"]["action"] == "tap"
            assert relayed["data"]["x"] == 0.4
            assert relayed["data"]["y"] == 0.6
            assert relayed["data"]["seq"] == 7

            await viewer.send_to(
                text_data=json.dumps(
                    {"type": "screen.control", "data": {"action": "keylog", "keys": "secret"}}
                )
            )
            invalid = json.loads(await viewer.receive_from())
            assert invalid["type"] == "screen.control_nack"
            assert invalid["reason"] == "invalid"

            await publisher.disconnect()
            await viewer.disconnect()

        asyncio.run(_run())
