"""Poll Zoho Mail IMAP and create BUILDING portal announcements (all residents)."""

import os
import time

from django.core.management.base import BaseCommand

from apps.integrations.zoho_announcements import ZohoConfig, sync_zoho_announcements


class Command(BaseCommand):
    help = "Poll Zoho Mail → portal Announcement (all-residents → building)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One cycle then exit")
        parser.add_argument("--interval", type=int, default=0, help="Seconds between cycles")
        parser.add_argument("--limit", type=int, default=25, help="Max inbox messages per cycle")

    def handle(self, *args, **options):
        interval = options["interval"] or int(os.environ.get("ZOHO_POLL_INTERVAL", "60"))
        limit = options["limit"]
        self.stdout.write(
            f"Zoho announcements poller started interval={interval}s limit={limit}"
        )
        self.stdout.flush()

        while True:
            if ZohoConfig.from_env() is None:
                self.stdout.write(
                    "zoho sync skipped: ZOHO_IMAP_USER / ZOHO_IMAP_PASSWORD / "
                    "ZOHO_ALL_RESIDENTS_ADDRESS not set"
                )
            else:
                try:
                    stats = sync_zoho_announcements(limit=limit)
                    self.stdout.write(
                        "zoho sync: "
                        f"fetched={stats['fetched']} created={stats['created']} "
                        f"skipped={stats['skipped']} errors={stats['errors']}"
                    )
                except Exception as exc:  # noqa: BLE001
                    self.stdout.write(self.style.ERROR(f"Zoho poll error: {exc}"))
            self.stdout.flush()
            if options["once"]:
                return
            time.sleep(max(interval, 5))
