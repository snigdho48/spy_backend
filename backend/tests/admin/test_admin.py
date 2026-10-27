"""Operator admin registration: every concrete app model, no secret columns."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.apps import apps
from django.contrib import admin
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import RefreshTokenRecord, SocialAccount, User
from apps.audit.models import AuditLog
from apps.devices.models import (
    ConsentRecord,
    Device,
    DevicePairing,
    SafeZone,
    ScreenShareSession,
    SharingPause,
    WatchlistKeyword,
)
from apps.events.models import DeviceEvent
from apps.tenants.models import Tenant, TenantMembership
from core.infrastructure.models.base import BaseModel, TenantScopedModel

LOCAL_APP_LABELS = ("accounts", "tenants", "devices", "events", "audit")
SECRET_LIST_COLUMNS = frozenset(
    {
        "password",
        "pairing_token",
        "pairing_code",
        "jti",
        "replaced_by_jti",
        "token",
    }
)


def _flatten_fieldsets(fieldsets) -> set[str]:
    names: set[str] = set()
    for _title, options in fieldsets:
        for field in options["fields"]:
            if isinstance(field, (list, tuple)):
                names.update(field)
            else:
                names.add(field)
    return names


def _list_display_names(model_admin) -> set[str]:
    names: set[str] = set()
    for item in model_admin.list_display:
        if isinstance(item, str):
            names.add(item)
        else:
            names.add(getattr(item, "__name__", ""))
    return names


@pytest.mark.django_db
def test_concrete_app_models_are_registered():
    seen = []
    for label in LOCAL_APP_LABELS:
        for model in apps.get_app_config(label).get_models():
            seen.append(model)
            assert admin.site.is_registered(model), model.__name__
            model_admin = admin.site.get_model_admin(model)
            leaked = _list_display_names(model_admin) & SECRET_LIST_COLUMNS
            assert not leaked, f"{model.__name__} lists secrets: {sorted(leaked)}"
    assert seen, "expected local models"


@pytest.mark.django_db
def test_abstract_bases_are_not_registered():
    assert not admin.site.is_registered(BaseModel)
    assert not admin.site.is_registered(TenantScopedModel)


@pytest.mark.django_db
def test_user_admin_uses_email_and_password_form():
    user_admin = admin.site.get_model_admin(User)
    change_fields = _flatten_fieldsets(user_admin.fieldsets)
    add_fields = _flatten_fieldsets(user_admin.add_fieldsets)

    assert {
        "email",
        "full_name",
        "is_staff",
        "is_superuser",
        "is_active",
        "password",
    } <= change_fields
    assert "username" not in change_fields
    assert "username" not in add_fields
    assert {"email", "password1", "password2", "full_name"} <= add_fields
    assert user_admin.add_form.Meta.model is User
    assert user_admin.form.Meta.model is User
    assert "username" not in user_admin.ordering
    assert "username" not in user_admin.search_fields
    assert any(
        getattr(pattern, "name", None) == "auth_user_password_change"
        for pattern in user_admin.get_urls()
    )


@pytest.fixture
def staff_client(client, settings):
    # Test settings inherit the production manifest storage, which 500s admin
    # pages unless collectstatic has been run. These tests only need the HTML.
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    User.objects.create_superuser("admin@example.com", "SecurePass123!")
    client.force_login(User.objects.get(email="admin@example.com"))
    return client


@pytest.mark.django_db
def test_staff_can_open_every_changelist(staff_client):
    index = staff_client.get(reverse("admin:index"))
    assert index.status_code == 200

    for label in LOCAL_APP_LABELS:
        for model in apps.get_app_config(label).get_models():
            url = reverse(
                f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist"
            )
            response = staff_client.get(url)
            assert response.status_code == 200, url


@pytest.mark.django_db
def test_add_user_and_change_password_from_admin(staff_client):
    inline_prefixes = ("tenant_memberships", "social_accounts")
    inline_data = {}
    for prefix in inline_prefixes:
        inline_data[f"{prefix}-TOTAL_FORMS"] = "0"
        inline_data[f"{prefix}-INITIAL_FORMS"] = "0"
        inline_data[f"{prefix}-MIN_NUM_FORMS"] = "0"
        inline_data[f"{prefix}-MAX_NUM_FORMS"] = "1000"

    add_response = staff_client.post(
        reverse("admin:accounts_user_add"),
        {
            "email": "ops@example.com",
            "full_name": "Ops User",
            "usable_password": "true",
            "password1": "AnotherPass123!",
            "password2": "AnotherPass123!",
            "is_staff": "on",
            "is_active": "on",
            **inline_data,
        },
    )
    assert add_response.status_code == 302, getattr(add_response, "context", None)
    created = User.objects.get(email="ops@example.com")
    assert created.full_name == "Ops User"
    assert created.check_password("AnotherPass123!")
    assert created.is_staff is True
    assert created.is_superuser is False
    assert created.is_active is True

    change = staff_client.get(reverse("admin:accounts_user_change", args=[created.pk]))
    assert change.status_code == 200
    body = change.content.decode()
    assert "../password/" in body or "password/" in body
    assert "AnotherPass123!" not in body

    password_response = staff_client.post(
        reverse("admin:auth_user_password_change", args=[created.pk]),
        {
            "password1": "RotatedPass123!",
            "password2": "RotatedPass123!",
            "usable_password": "true",
            "set-password": "Change password",
        },
    )
    assert password_response.status_code == 302
    created.refresh_from_db()
    assert created.check_password("RotatedPass123!")

    old_hash = created.password
    edit = staff_client.post(
        reverse("admin:accounts_user_change", args=[created.pk]),
        {
            "email": created.email,
            "full_name": "Renamed Ops",
            "is_staff": "on",
            "is_active": "on",
            **inline_data,
        },
    )
    assert edit.status_code == 302, edit.content.decode()[:2000]
    created.refresh_from_db()
    assert created.full_name == "Renamed Ops"
    assert created.password == old_hash


@pytest.mark.django_db
def test_changelist_hides_pairing_and_refresh_secrets(staff_client):
    now = timezone.now()
    owner = User.objects.create_user("owner@example.com", "SecurePass123!")
    tenant = Tenant.objects.create(name="Ops Org", slug="ops-org")
    device = Device.objects.create(
        tenant=tenant,
        owner=owner,
        name="Pixel",
        platform=Device.Platform.ANDROID,
        device_fingerprint="fp-1",
        status=Device.Status.ACTIVE,
    )
    pairing = DevicePairing.objects.create(tenant=tenant, device=device)
    record = RefreshTokenRecord.objects.create(
        user=owner,
        jti=f"jti-{uuid4()}",
        expires_at=now + timedelta(days=1),
        replaced_by_jti="replaced-jti-secret",
    )

    pairing_list = staff_client.get(reverse("admin:devices_devicepairing_changelist"))
    assert pairing_list.status_code == 200
    pairing_html = pairing_list.content.decode()
    assert pairing.pairing_token not in pairing_html
    assert pairing.pairing_code not in pairing_html

    pairing_change = staff_client.get(
        reverse("admin:devices_devicepairing_change", args=[pairing.pk])
    )
    assert pairing_change.status_code == 200
    pairing_detail = pairing_change.content.decode()
    assert pairing.pairing_token in pairing_detail
    assert pairing.pairing_code in pairing_detail

    token_list = staff_client.get(reverse("admin:accounts_refreshtokenrecord_changelist"))
    assert token_list.status_code == 200
    assert record.jti not in token_list.content.decode()
    token_change = staff_client.get(
        reverse("admin:accounts_refreshtokenrecord_change", args=[record.pk])
    )
    assert token_change.status_code == 200
    assert record.jti in token_change.content.decode()


@pytest.mark.django_db
def test_event_and_audit_change_pages_are_inspect_only(staff_client):
    now = timezone.now()
    owner = User.objects.create_user("monitor@example.com", "SecurePass123!")
    tenant = Tenant.objects.create(name="Audit Org", slug="audit-org")
    TenantMembership.objects.create(
        tenant=tenant,
        user=owner,
        role=TenantMembership.Role.OWNER,
    )
    device = Device.objects.create(
        tenant=tenant,
        owner=owner,
        name="Phone",
        platform=Device.Platform.IOS,
        device_fingerprint="fp-2",
    )
    SharingPause.objects.create(
        tenant=tenant,
        device=device,
        started_at=now,
        expires_at=now + timedelta(hours=1),
        created_by=owner,
    )
    WatchlistKeyword.objects.create(tenant=tenant, word="emergency", created_by=owner)
    SafeZone.objects.create(
        tenant=tenant,
        name="Home",
        lat=1.0,
        lng=2.0,
        created_by=owner,
        device=device,
    )
    ConsentRecord.objects.create(
        tenant=tenant,
        device=device,
        granted_by=owner,
        scopes=["location"],
        consent_version="1.0.0",
    )
    ScreenShareSession.objects.create(
        tenant=tenant,
        device=device,
        requested_by=owner,
        requested_at=now,
    )
    SocialAccount.objects.create(
        user=owner,
        provider=SocialAccount.Provider.GOOGLE,
        provider_uid="google-subject",
        email=owner.email,
    )
    event = DeviceEvent.objects.create(
        tenant=tenant,
        device=device,
        event_type="location",
        payload={"lat": 1},
        event_timestamp=now,
    )
    audit = AuditLog.objects.create(
        tenant=tenant,
        actor=owner,
        action="device.paired",
        resource_type="device",
        resource_id=device.id,
        metadata={"pairing_code": "ABC-DEF"},
    )

    for label in LOCAL_APP_LABELS:
        for model in apps.get_app_config(label).get_models():
            obj = model.objects.first()
            if obj is None:
                continue
            url = reverse(
                f"admin:{model._meta.app_label}_{model._meta.model_name}_change",
                args=[obj.pk],
            )
            response = staff_client.get(url)
            assert response.status_code == 200, url

    event_admin = admin.site.get_model_admin(DeviceEvent)
    audit_admin = admin.site.get_model_admin(AuditLog)
    assert event_admin.has_add_permission(None) is False
    assert audit_admin.has_add_permission(None) is False
    assert "payload" not in event_admin.list_display
    assert "metadata" not in audit_admin.list_display

    event_list = staff_client.get(reverse("admin:events_deviceevent_changelist"))
    assert '"lat"' not in event_list.content.decode()
    audit_list = staff_client.get(reverse("admin:audit_auditlog_changelist"))
    assert "ABC-DEF" not in audit_list.content.decode()

    event_change = staff_client.get(reverse("admin:events_deviceevent_change", args=[event.pk]))
    assert "&quot;lat&quot;" in event_change.content.decode() or '"lat"' in event_change.content.decode()
    audit_change = staff_client.get(reverse("admin:audit_auditlog_change", args=[audit.pk]))
    assert "ABC-DEF" in audit_change.content.decode()
