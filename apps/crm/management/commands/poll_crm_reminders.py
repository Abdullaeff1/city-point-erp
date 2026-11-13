"""Poll CRM lead idle + offer follow-up reminders."""

import os
import time

from django.core.management.base import BaseCommand

from apps.crm.services import scan_crm_reminders


class Command(BaseCommand):
    help = "Scan CRM leads/offers → idempotent in-app reminders (1d / 3d)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One cycle then exit")
        parser.add_argument("--interval", type=int, default=0, help="Seconds between cycles")
        parser.add_argument("--limit", type=int, default=200, help="Max rows per scan")

    def handle(self, *args, **options):
        interval = options["interval"] or int(os.environ.get("CRM_REMINDER_POLL_INTERVAL", "300"))
        limit = options["limit"]
        self.stdout.write(f"CRM reminder poller interval={interval}s limit={limit}")
        self.stdout.flush()
        while True:
            try:
                stats = scan_crm_reminders(limit=limit)
                self.stdout.write(
                    "crm reminders: "
                    f"leads_checked={stats['leads_checked']} leads_reminded={stats['leads_reminded']} "
                    f"offers_checked={stats['offers_checked']} offers_reminded={stats['offers_reminded']}"
                )
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"CRM poll error: {exc}"))
            self.stdout.flush()
            if options["once"]:
                return
            time.sleep(max(interval, 60))
