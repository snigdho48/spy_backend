"""Celery tasks for the events app."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="events.purge_expired_events")
def purge_expired_events(chunk_size: int = 500) -> dict:
    """Periodic retention enforcement — safe to run repeatedly."""
    from apps.events.application.services.retention_service import RetentionService

    result = RetentionService().purge_all(chunk_size=chunk_size)
    logger.info("purge_expired_events finished: %s", result)
    return result
