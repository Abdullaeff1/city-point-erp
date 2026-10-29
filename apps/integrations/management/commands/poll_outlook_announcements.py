"""Poll shared Outlook mailbox and create BUILDING portal announcements."""

import os
import time

from django.core.management.base import BaseCommand

from apps.integrations.outlook_announcements import OutlookConfig, sync_outlook_announcements


class Command(BaseCommand):
    help = "Poll Outlook shared mailbox → portal Announcement (+ attachments)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One cycle then exit")
        parser.add_argument("--interval", type=int, default=0, help="Seconds between cycles")
        parser.add_argument("--top", type=int, default=25, help="Max inbox messages per cycle")

    def handle(self, *args, **options):
        interval = options["interval"] or int(os.environ.get("OUTLOOK_POLL_INTERVAL", "60"))
        top = options["top"]
        self.stdout.write(
            f"Outlook announcements poller started interval={interval}s top={top}"
        )
        self.stdout.flush()

        while True:
            if OutlookConfig.from_env() is None:
                self.stdout.write(
                    "outlook sync skipped: OUTLOOK_TENANT_ID / CLIENT_ID / "
                    "CLIENT_SECRET / MAILBOX not set"
                )
            else:
                try:
                    stats = sync_outlook_announcements(top=top)
                    self.stdout.write(
                        "outlook sync: "
                        f"fetched={stats['fetched']} created={stats['created']} "
                        f"skipped={stats['skipped']} errors={stats['errors']}"
                    )
                except Exception as exc:  # noqa: BLE001
                    self.stdout.write(self.style.ERROR(f"Outlook poll error: {exc}"))
            self.stdout.flush()
            if options["once"]:
                return
            time.sleep(max(interval, 5))
