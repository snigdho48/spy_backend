"""Celery tasks for alert push delivery."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="alerts.push_alert_notification", ignore_result=True)
def push_alert_notification(alert_id: str) -> dict:
    from apps.alerts.application.services.alert_service import PushTokenService
    from apps.alerts.application.services.fcm import FCMClient
    from apps.alerts.infrastructure.models.alert import Alert

    alert = (
        Alert.objects.filter(pk=alert_id).select_related("device").first()
    )
    if not alert:
        return {"ok": False, "reason": "alert_missing"}

    client = FCMClient()
    tokens = PushTokenService().tokens_for_device_monitors(alert.device)
    results = []
    for push in tokens:
        result = client.send(
            token=push.token,
            title=alert.title,
            body=alert.body,
            data={
                "alert_id": str(alert.id),
                "type": alert.type,
                "severity": alert.severity,
                "device_id": str(alert.device_id),
            },
        )
        results.append({"token_id": str(push.id), **result})
    logger.info(
        "push_alert_notification alert=%s tokens=%s",
        alert_id,
        len(results),
    )
    return {"ok": True, "sent": len(results), "results": results}
