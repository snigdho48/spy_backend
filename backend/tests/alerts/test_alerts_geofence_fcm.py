"""Geofence enter/exit debounce, alert generation paths, push tokens + FCM."""

from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.alerts.infrastructure.models.alert import Alert, PushToken
from apps.devices.application.services.geofence_service import (
    GeofenceService,
    haversine_m,
)
from apps.devices.infrastructure.models.device import (
    ConsentRecord,
    Device,
    GeofenceState,
    SafeZone,
)
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


def _add_member(owner_data, email, role):
    from apps.accounts.infrastructure.models.user import User
    from apps.tenants.infrastructure.models.tenant import Tenant

    client = APIClient()
    data = _register(client, email, f"Tmp-{email}")
    user = User.objects.get(email=email)
    TenantMembership.objects.filter(user=user).delete()
    Tenant.objects.filter(id=data["tenant"]["id"]).delete()
    TenantMembership.objects.create(
        tenant_id=owner_data["tenant"]["id"], user=user, role=role
    )
    login = client.post(
        reverse("auth-login"),
        {"email": email, "password": "SecurePass123!"},
        format="json",
    )
    assert login.status_code == status.HTTP_200_OK
    return {
        "user": {"id": str(user.id), "email": email},
        "tokens": {"access": login.data["access"]},
        "tenant": owner_data["tenant"],
    }


def _seed_device(owner_data, scopes, fingerprint="fp-al-1"):
    device = Device.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        owner_id=owner_data["user"]["id"],
        name="Monitored",
        platform="android",
        device_fingerprint=fingerprint,
        status=Device.Status.ACTIVE,
    )
    ConsentRecord.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        device=device,
        granted_by_id=owner_data["user"]["id"],
        scopes=scopes,
        consent_version="1.0.0",
    )
    return device


def _ingest(api_client, device_id, events):
    return api_client.post(
        reverse("event-ingest"),
        {"device_id": str(device_id), "events": events},
        format="json",
    )


@pytest.mark.django_db
class TestGeofenceEvaluation:
    def test_haversine_zero(self):
        assert haversine_m(23.8, 90.4, 23.8, 90.4) == 0.0

    def test_enter_exit_debounce(self, api_client):
        owner = _register(api_client, "gz-o@example.com", "GZ O")
        device = _seed_device(owner, ["location"], "fp-gz-1")
        zone = SafeZone.objects.create(
            tenant_id=owner["tenant"]["id"],
            name="Home",
            lat=23.8103,
            lng=90.4125,
            radius_m=100,
            enabled=True,
            created_by_id=owner["user"]["id"],
            device=device,
        )
        svc = GeofenceService()

        t1 = svc.evaluate_location(device=device, lat=23.8103, lng=90.4125)
        assert t1 == []
        state = GeofenceState.objects.get(device=device, safe_zone=zone)
        assert state.is_inside is True

        t2 = svc.evaluate_location(device=device, lat=23.8104, lng=90.4126)
        assert t2 == []

        t3 = svc.evaluate_location(device=device, lat=23.9000, lng=90.5000)
        assert len(t3) == 1
        assert t3[0]["transition"] == "exit"

        t4 = svc.evaluate_location(device=device, lat=23.8103, lng=90.4125)
        assert len(t4) == 1
        assert t4[0]["transition"] == "enter"

    def test_disabled_zone_skipped(self, api_client):
        owner = _register(api_client, "gz-d@example.com", "GZ D")
        device = _seed_device(owner, ["location"], "fp-gz-2")
        SafeZone.objects.create(
            tenant_id=owner["tenant"]["id"],
            name="Off",
            lat=0.0,
            lng=0.0,
            radius_m=50,
            enabled=False,
            created_by_id=owner["user"]["id"],
            device=device,
        )
        assert GeofenceService().evaluate_location(
            device=device, lat=0.0, lng=0.0
        ) == []

    def test_safe_zone_enabled_roundtrip(self, api_client):
        owner = _register(api_client, "gz-e@example.com", "GZ E")
        _auth(api_client, owner["tokens"])
        create = api_client.post(
            reverse("safe-zone-list"),
            {
                "name": "School",
                "lat": 23.7,
                "lng": 90.4,
                "radius_m": 200,
                "enabled": False,
            },
            format="json",
        )
        assert create.status_code == status.HTTP_201_CREATED, create.data
        assert create.data["enabled"] is False
        zone_id = create.data["id"]
        patch = api_client.patch(
            reverse("safe-zone-detail", kwargs={"zone_id": zone_id}),
            {"enabled": True},
            format="json",
        )
        assert patch.status_code == status.HTTP_200_OK
        assert patch.data["enabled"] is True


@pytest.mark.django_db
class TestAlertGeneration:
    @patch("apps.alerts.tasks.push_alert_notification.delay")
    def test_location_generates_geofence_alerts(self, mock_delay, api_client):
        owner = _register(api_client, "ag-g@example.com", "AG G")
        device = _seed_device(owner, ["location"], "fp-ag-1")
        SafeZone.objects.create(
            tenant_id=owner["tenant"]["id"],
            name="Home",
            lat=23.8103,
            lng=90.4125,
            radius_m=100,
            enabled=True,
            created_by_id=owner["user"]["id"],
            device=device,
        )
        _auth(api_client, owner["tokens"])
        _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "location.update",
                    "payload": {"lat": 23.8103, "lng": 90.4125},
                    "idempotency_key": "loc-1",
                }
            ],
        )
        assert Alert.objects.count() == 0
        _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "location.update",
                    "payload": {"lat": 23.9000, "lng": 90.5000},
                    "idempotency_key": "loc-2",
                }
            ],
        )
        alerts = list(Alert.objects.filter(device=device))
        assert len(alerts) == 1
        assert alerts[0].type == Alert.Type.GEOFENCE_EXIT
        assert mock_delay.called

    @patch("apps.alerts.tasks.push_alert_notification.delay")
    def test_app_installed_diff(self, mock_delay, api_client):
        owner = _register(api_client, "ag-a@example.com", "AG A")
        device = _seed_device(owner, ["app_usage"], "fp-ag-2")
        _auth(api_client, owner["tokens"])
        _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "app_inventory.snapshot",
                    "payload": {
                        "apps": [{"package": "com.a", "app_name": "A"}]
                    },
                    "idempotency_key": "inv-1",
                }
            ],
        )
        assert Alert.objects.filter(type=Alert.Type.APP_INSTALLED).count() == 0
        _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "app_inventory.snapshot",
                    "payload": {
                        "apps": [
                            {"package": "com.a", "app_name": "A"},
                            {"package": "com.b", "app_name": "B"},
                        ]
                    },
                    "idempotency_key": "inv-2",
                }
            ],
        )
        apps = list(Alert.objects.filter(type=Alert.Type.APP_INSTALLED))
        assert len(apps) == 1
        assert apps[0].metadata["package"] == "com.b"

    @patch("apps.alerts.tasks.push_alert_notification.delay")
    def test_sim_changed(self, mock_delay, api_client):
        owner = _register(api_client, "ag-s@example.com", "AG S")
        device = _seed_device(owner, ["sim"], "fp-ag-3")
        _auth(api_client, owner["tokens"])
        res = _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "sim.changed",
                    "payload": {"iccid": "8901", "carrier": "X"},
                    "idempotency_key": "sim-1",
                }
            ],
        )
        assert res.data["accepted"] == 1
        assert Alert.objects.filter(type=Alert.Type.SIM_CHANGED).count() == 1

    @patch("apps.alerts.tasks.push_alert_notification.delay")
    def test_low_battery(self, mock_delay, api_client):
        owner = _register(api_client, "ag-b@example.com", "AG B")
        device = _seed_device(owner, ["telemetry"], "fp-ag-4")
        _auth(api_client, owner["tokens"])
        _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "device.telemetry",
                    "payload": {"battery_pct": 10, "charging": False},
                    "idempotency_key": "bat-1",
                }
            ],
        )
        assert Alert.objects.filter(type=Alert.Type.LOW_BATTERY).count() == 1
        _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "device.telemetry",
                    "payload": {"battery_pct": 8, "charging": False},
                    "idempotency_key": "bat-2",
                }
            ],
        )
        assert Alert.objects.filter(type=Alert.Type.LOW_BATTERY).count() == 1
        Alert.objects.all().update(read_at=timezone.now())
        _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "device.telemetry",
                    "payload": {"battery_pct": 5, "charging": True},
                    "idempotency_key": "bat-3",
                }
            ],
        )
        assert (
            Alert.objects.filter(
                type=Alert.Type.LOW_BATTERY, read_at__isnull=True
            ).count()
            == 0
        )

    @patch("apps.alerts.tasks.push_alert_notification.delay")
    def test_sos(self, mock_delay, api_client):
        owner = _register(api_client, "ag-sos@example.com", "AG SOS")
        device = _seed_device(owner, ["sos"], "fp-ag-5")
        _auth(api_client, owner["tokens"])
        res = _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "sos.triggered",
                    "payload": {"source": "button"},
                    "idempotency_key": "sos-1",
                }
            ],
        )
        assert res.data["accepted"] == 1
        alert = Alert.objects.get(type=Alert.Type.SOS)
        assert alert.severity == Alert.Severity.CRITICAL


@pytest.mark.django_db
class TestAlertEndpoints:
    @patch("apps.alerts.tasks.push_alert_notification.delay")
    def test_list_mark_read_delete(self, mock_delay, api_client):
        owner = _register(api_client, "ae-o@example.com", "AE O")
        device = _seed_device(owner, ["sos"], "fp-ae-1")
        _auth(api_client, owner["tokens"])
        _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "sos.triggered",
                    "payload": {},
                    "idempotency_key": "ae-sos",
                }
            ],
        )
        listing = api_client.get(reverse("alert-list"))
        assert listing.status_code == status.HTTP_200_OK
        assert listing.data["count"] == 1
        alert_id = listing.data["results"][0]["id"]

        unread = api_client.get(reverse("alert-list"), {"unread": "true"})
        assert unread.data["count"] == 1

        marked = api_client.post(
            reverse("alert-read", kwargs={"alert_id": alert_id})
        )
        assert marked.status_code == status.HTTP_200_OK
        assert marked.data["is_read"] is True

        deleted = api_client.delete(
            reverse("alert-delete", kwargs={"alert_id": alert_id})
        )
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert Alert.objects.count() == 0

    @patch("apps.alerts.tasks.push_alert_notification.delay")
    def test_mark_all_read(self, mock_delay, api_client):
        owner = _register(api_client, "ae-m@example.com", "AE M")
        device = _seed_device(owner, ["sos"], "fp-ae-2")
        _auth(api_client, owner["tokens"])
        for i in range(3):
            _ingest(
                api_client,
                device.id,
                [
                    {
                        "event_type": "sos.triggered",
                        "payload": {},
                        "idempotency_key": f"ae-m-{i}",
                    }
                ],
            )
        res = api_client.post(reverse("alert-read-all"))
        assert res.status_code == status.HTTP_200_OK
        assert res.data["marked"] == 3

    @patch("apps.alerts.tasks.push_alert_notification.delay")
    def test_viewer_can_list_not_delete(self, mock_delay, api_client):
        owner = _register(api_client, "ae-ow@example.com", "AE OW")
        device = _seed_device(owner, ["sos"], "fp-ae-3")
        _auth(api_client, owner["tokens"])
        _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "sos.triggered",
                    "payload": {},
                    "idempotency_key": "ae-v",
                }
            ],
        )
        alert_id = str(Alert.objects.get().id)
        viewer = _add_member(
            owner, "ae-v@example.com", TenantMembership.Role.VIEWER
        )
        _auth(api_client, viewer["tokens"])
        listing = api_client.get(
            reverse("alert-list"), {"device_id": str(device.id)}
        )
        assert listing.status_code == status.HTTP_403_FORBIDDEN
        deleted = api_client.delete(
            reverse("alert-delete", kwargs={"alert_id": alert_id})
        )
        assert deleted.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestPushTokensAndFcm:
    def test_register_unregister(self, api_client):
        owner = _register(api_client, "pt-o@example.com", "PT O")
        _auth(api_client, owner["tokens"])
        reg = api_client.post(
            reverse("push-token-register"),
            {"token": "fcm-token-abc", "platform": "android"},
            format="json",
        )
        assert reg.status_code == status.HTTP_201_CREATED, reg.data
        token_id = reg.data["id"]
        assert PushToken.objects.filter(token="fcm-token-abc").exists()
        reg2 = api_client.post(
            reverse("push-token-register"),
            {"token": "fcm-token-abc", "platform": "android"},
            format="json",
        )
        assert reg2.status_code == status.HTTP_201_CREATED
        assert PushToken.objects.filter(token="fcm-token-abc").count() == 1

        unreg = api_client.delete(
            reverse("push-token-unregister", kwargs={"token_id": token_id})
        )
        assert unreg.status_code == status.HTTP_200_OK
        assert unreg.data["deleted"] == 1

    @patch("apps.alerts.tasks.push_alert_notification.delay")
    def test_task_enqueued_on_alert(self, mock_delay, api_client):
        owner = _register(api_client, "pt-t@example.com", "PT T")
        device = _seed_device(owner, ["sos"], "fp-pt-1")
        _auth(api_client, owner["tokens"])
        _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "sos.triggered",
                    "payload": {},
                    "idempotency_key": "pt-sos",
                }
            ],
        )
        assert mock_delay.call_count == 1

    def test_fcm_noop_without_creds(self):
        from apps.alerts.application.services.fcm import FCMClient

        client = FCMClient(credentials_path="")
        result = client.send(token="x", title="t", body="b")
        assert result["skipped"] is True

    def test_push_task_sends_to_tokens(self, api_client):
        owner = _register(api_client, "pt-f@example.com", "PT F")
        device = _seed_device(owner, ["sos"], "fp-pt-2")
        PushToken.objects.create(
            tenant_id=owner["tenant"]["id"],
            user_id=owner["user"]["id"],
            token="tok-1",
            platform="android",
        )
        alert = Alert.objects.create(
            tenant_id=owner["tenant"]["id"],
            device=device,
            type=Alert.Type.SOS,
            severity=Alert.Severity.CRITICAL,
            title="SOS",
            body="help",
        )
        mock_client = MagicMock()
        mock_client.send.return_value = {"ok": True}
        with patch(
            "apps.alerts.application.services.fcm.FCMClient",
            return_value=mock_client,
        ):
            from apps.alerts.tasks import push_alert_notification

            result = push_alert_notification(str(alert.id))
        assert result["ok"] is True
        assert result["sent"] == 1
        mock_client.send.assert_called_once()
