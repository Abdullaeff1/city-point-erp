"""Poll lease start activation + expiry notice window."""

import os
import time

from django.core.management.base import BaseCommand

from apps.leases.services import process_lease_lifecycle


class Command(BaseCommand):
    help = "SIGNED→ACTIVE on start_date; ACTIVE→EXPIRING near end_date (+ notify)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One cycle then exit")
        parser.add_argument("--interval", type=int, default=0, help="Seconds between cycles")
        parser.add_argument(
            "--expiring-days",
            type=int,
            default=0,
            help="Notice window days (default LEASE_EXPIRING_NOTICE_DAYS)",
        )

    def handle(self, *args, **options):
        interval = options["interval"] or int(
            os.environ.get("LEASE_LIFECYCLE_POLL_INTERVAL", "3600")
        )
        expiring_days = options["expiring_days"] or None
        self.stdout.write(f"Lease lifecycle poller interval={interval}s")
        self.stdout.flush()
        while True:
            try:
                stats = process_lease_lifecycle(expiring_days=expiring_days)
                self.stdout.write(
                    "lease lifecycle: "
                    f"as_of={stats['as_of']} activated={stats['activated']} "
                    f"marked_expiring={stats['marked_expiring']} "
                    f"expiring_days={stats['expiring_days']}"
                )
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"Lease lifecycle error: {exc}"))
            self.stdout.flush()
            if options["once"]:
                return
            time.sleep(max(interval, 60))
