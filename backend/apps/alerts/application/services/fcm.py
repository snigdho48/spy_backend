"""Lightweight FCM HTTP v1 sender (no firebase-admin / grpcio).

Reads a Google service-account JSON from ``FCM_CREDENTIALS_PATH`` (or
``GOOGLE_APPLICATION_CREDENTIALS``). When the path is unset / unreadable the
sender is a no-op so local/dev/tests stay quiet without credentials.

Uses ``google-auth`` (already in requirements) for a JWT-based access token
and plain ``requests`` for the HTTP v1 ``messages:send`` call.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_SEND_URL = (
    "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
)


class FCMClient:
    """Thin wrapper around FCM HTTP v1. Instantiable / mockable in tests."""

    def __init__(self, credentials_path: str | None = None) -> None:
        self.credentials_path = (
            credentials_path
            or getattr(settings, "FCM_CREDENTIALS_PATH", "")
            or os.environ.get("FCM_CREDENTIALS_PATH", "")
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        ).strip()
        self._creds = None
        self._project_id: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.credentials_path) and os.path.isfile(
            self.credentials_path
        )

    def _load(self):
        if self._creds is not None:
            return
        if not self.enabled:
            return
        from google.oauth2 import service_account

        info = json.loads(open(self.credentials_path, encoding="utf-8").read())
        self._project_id = info.get("project_id")
        self._creds = service_account.Credentials.from_service_account_info(
            info, scopes=[_FCM_SCOPE]
        )

    def send(
        self,
        *,
        token: str,
        title: str,
        body: str = "",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send one notification. Returns a status dict; never raises for FCM errors."""
        if not self.enabled:
            return {"ok": False, "skipped": True, "reason": "fcm_disabled"}
        try:
            self._load()
            if not self._creds or not self._project_id:
                return {"ok": False, "skipped": True, "reason": "no_credentials"}
            from google.auth.transport.requests import Request as GoogleRequest

            self._creds.refresh(GoogleRequest())
            access_token = self._creds.token
            payload = {
                "message": {
                    "token": token,
                    "notification": {"title": title, "body": body},
                    "data": {
                        k: str(v) for k, v in (data or {}).items() if v is not None
                    },
                }
            }
            resp = requests.post(
                _SEND_URL.format(project_id=self._project_id),
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json=payload,
                timeout=10,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "FCM send failed status=%s", resp.status_code
                )
                return {
                    "ok": False,
                    "status": resp.status_code,
                    "body": resp.text[:500],
                }
            return {"ok": True, "status": resp.status_code, "body": resp.json()}
        except Exception as exc:
            logger.exception("FCM send error")
            return {"ok": False, "error": str(exc)}
