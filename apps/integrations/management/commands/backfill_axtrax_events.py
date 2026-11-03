"""Backfill AccessEvent archive from AxTraxNG starting at a calendar date."""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.integrations.axtrax_events_sync import backfill_denied_since, backfill_events_from_date


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
        parser.add_argument(
            "--denied",
            action="store_true",
            help="Yalnız Access Denied (tip 18/33) backfill — AxTrax Events ilə uyğunluq üçün",
        )

    def handle(self, *args, **options):
        raw = (options.get("from_date") or "").strip()
        try:
            day = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("Use --from=YYYY-MM-DD") from exc
        start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
        batch = int(options["batch_size"])
        if options.get("denied"):
            self.stdout.write(f"Denied backfill from {day.isoformat()} …")
            self.stdout.flush()
            totals = backfill_denied_since(start, batch_size=batch)
        else:
            self.stdout.write(f"Backfill from {day.isoformat()} …")
            self.stdout.flush()
            totals = backfill_events_from_date(start, batch_size=batch)
        self.stdout.write(self.style.SUCCESS(str(totals)))
