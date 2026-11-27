"""Poll guest overdue cases past check-in + 24h and notify the right audience.

Cases (distinct):
1. Cardless INSIDE → company portal residents (resident-managed checkout).
2. INSIDE + ID held → every active Reception and Security user.
3. Known departure + ID still held → RETURN_PENDING (event handlers, not this poller).
"""

import os
import time

from django.core.management.base import BaseCommand

from apps.reception.services import process_guest_overdue_alerts


class Command(BaseCommand):
    help = (
        "In-app overdue alerts: cardless→portal and ID-held→Reception/Security "
        "(one notification per recipient × visit × alert type; idempotent)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One cycle then exit")
        parser.add_argument("--interval", type=int, default=0, help="Seconds between cycles")

    def handle(self, *args, **options):
        interval = options["interval"] or int(
            os.environ.get("GUEST_CHECKOUT_OVERDUE_POLL_INTERVAL", "900")
        )
        self.stdout.write(f"Guest overdue poller interval={interval}s")
        self.stdout.flush()
        while True:
            try:
                stats = process_guest_overdue_alerts()
                self.stdout.write(
                    "guest overdue: "
                    f"as_of={stats['as_of']} "
                    f"portal_visits={stats['portal_visits']} "
                    f"portal_notes={stats['portal_notifications_created']} "
                    f"id_held_visits={stats['id_held_visits']} "
                    f"id_held_notes={stats['id_held_notifications_created']}"
                )
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"Guest overdue poll error: {exc}"))
            self.stdout.flush()
            if options["once"]:
                return
            time.sleep(max(interval, 60))