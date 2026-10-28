"""Manually purge events/snapshots past each tenant plan's retention window."""

from django.core.management.base import BaseCommand

from apps.events.application.services.retention_service import RetentionService


class Command(BaseCommand):
    help = (
        "Delete DeviceEvent / snapshot rows older than each tenant's plan "
        "retention (free=7d, pro=90d, enterprise=365d). Chunked and idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=500,
            help="Rows deleted per batch (default 500; keep small on 3GB hosts).",
        )

    def handle(self, *args, **options):
        chunk_size = options["chunk_size"]
        result = RetentionService().purge_all(chunk_size=chunk_size)
        self.stdout.write(self.style.SUCCESS(f"Purge complete: {result}"))
