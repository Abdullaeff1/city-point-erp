"""Poll open tickets for SLA risk/breach escalation notifications."""

import os
import time

from django.core.management.base import BaseCommand

from apps.tickets.services import scan_ticket_escalations


class Command(BaseCommand):
    help = "Scan tickets → escalate on SLA risk/breach (in-app + email outbox)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One cycle then exit")
        parser.add_argument("--interval", type=int, default=0, help="Seconds between cycles")
        parser.add_argument("--limit", type=int, default=500, help="Max tickets per cycle")

    def handle(self, *args, **options):
        interval = options["interval"] or int(os.environ.get("TICKET_SLA_POLL_INTERVAL", "120"))
        limit = options["limit"]
        self.stdout.write(f"Ticket SLA escalation poller interval={interval}s limit={limit}")
        self.stdout.flush()
        while True:
            try:
                stats = scan_ticket_escalations(limit=limit)
                self.stdout.write(
                    "sla escalation: "
                    f"checked={stats['checked']} escalated={stats['escalated']} "
                    f"risk={stats['risk']} breach={stats['breach']}"
                )
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"SLA poll error: {exc}"))
            self.stdout.flush()
            if options["once"]:
                return
            time.sleep(max(interval, 30))
