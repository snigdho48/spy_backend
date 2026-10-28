"""Outbound email helper — no-ops when SMTP is not configured."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def smtp_configured() -> bool:
    backend = getattr(settings, "EMAIL_BACKEND", "") or ""
    host = (getattr(settings, "EMAIL_HOST", "") or "").strip()
    # Console / locmem backends are treated as "configured" for local/dev so
    # messages still appear in logs; a blank EMAIL_HOST with SMTP backend is not.
    if "console" in backend or "locmem" in backend or "filebased" in backend:
        return True
    if "smtp" in backend.lower():
        return bool(host)
    return False


def send_invite_email(*, to_email: str, tenant_name: str, invite_link: str, role: str) -> bool:
    """Send an invite email when mail is configured. Returns True if attempted."""
    if not smtp_configured():
        logger.info(
            "Invite email skipped (SMTP unconfigured) to=%s tenant=%s",
            to_email,
            tenant_name,
        )
        return False

    subject = f"You're invited to join {tenant_name}"
    body = (
        f"You have been invited to join the workspace '{tenant_name}' "
        f"as {role}.\n\n"
        f"Accept the invite:\n{invite_link}\n\n"
        "If you did not expect this, you can ignore this message."
    )
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@localhost"
    try:
        send_mail(subject, body, from_email, [to_email], fail_silently=True)
        return True
    except Exception:
        logger.exception("Failed to send invite email to %s", to_email)
        return False
