"""Backfill AccessEvent archive from AxTraxNG starting at a calendar date."""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.integrations.axtrax_events_sync import backfill_events_from_date


class Command(BaseCommand):
    help = "AxTraxNG-dən verilmiş tarixdən etibarən giriş/çıxış hadisələrini ERP-yə çək (dedup ilə)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--from",
            dest="from_date",
            required=True,
            help="Start date YYYY-MM-DD (local), e.g. 2026-09-01",
        )
        parser.add_argument("--batch-size", type=int, default=5000)

    def handle(self, *args, **options):
        raw = (options.get("from_date") or "").strip()
        try:
            day = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("Use --from=YYYY-MM-DD") from exc
        start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
        self.stdout.write(f"Backfill from {day.isoformat()} …")
        self.stdout.flush()
        totals = backfill_events_from_date(start, batch_size=int(options["batch_size"]))
        self.stdout.write(self.style.SUCCESS(str(totals)))
