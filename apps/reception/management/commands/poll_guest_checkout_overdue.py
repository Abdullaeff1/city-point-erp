"""Poll portal cardless guest visits past check-in + 24h and notify members."""

import os
import time

from django.core.management.base import BaseCommand

from apps.reception.services import process_portal_checkout_overdue_alerts


class Command(BaseCommand):
    help = (
        "In-app overdue checkout alerts for eligible cardless portal visits "
        "(one notification per recipient × visit; idempotent)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One cycle then exit")
        parser.add_argument("--interval", type=int, default=0, help="Seconds between cycles")

    def handle(self, *args, **options):
        interval = options["interval"] or int(
            os.environ.get("GUEST_CHECKOUT_OVERDUE_POLL_INTERVAL", "900")
        )
        self.stdout.write(f"Guest checkout overdue poller interval={interval}s")
        self.stdout.flush()
        while True:
            try:
                stats = process_portal_checkout_overdue_alerts()
                self.stdout.write(
                    "guest checkout overdue: "
                    f"as_of={stats['as_of']} visits={stats['visits']} "
                    f"notifications_created={stats['notifications_created']}"
                )
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"Guest overdue poll error: {exc}"))
            self.stdout.flush()
            if options["once"]:
                return
            time.sleep(max(interval, 60))
