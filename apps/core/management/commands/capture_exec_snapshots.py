"""Capture daily executive KPI snapshots (M11) — not a database backup."""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.erp.exec_reports import capture_daily_snapshot


class Command(BaseCommand):
    help = "Store compact exec KPI snapshot for a date (default: today)."

    def add_arguments(self, parser):
        parser.add_argument("--date", default="", help="YYYY-MM-DD (default today)")
        parser.add_argument("--company-id", type=int, default=0)

    def handle(self, *args, **options):
        raw = (options.get("date") or "").strip()
        as_of = parse_date(raw) if raw else timezone.localdate()
        if not as_of:
            self.stderr.write("Invalid --date")
            return
        company_id = options.get("company_id") or None
        if company_id == 0:
            company_id = None
        obj = capture_daily_snapshot(as_of=as_of, company_id=company_id)
        self.stdout.write(
            self.style.SUCCESS(
                f"snapshot id={obj.pk} date={obj.snapshot_date} company={obj.company_id or 'all'}"
            )
        )
