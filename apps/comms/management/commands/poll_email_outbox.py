"""Periodically flush pending email outbox (ticket.* by default)."""

from __future__ import annotations

import os
import time

from django.core.management.base import BaseCommand

from apps.comms.services import flush_pending_email_dispatches


class Command(BaseCommand):
    help = "Loop: flush pending EMAIL NotificationDispatch (TICKET_EMAIL_OUTBOX_*)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--prefix", default="ticket.")
        parser.add_argument("--limit", type=int, default=50)

    def handle(self, *args, **options):
        interval = int(os.environ.get("TICKET_EMAIL_OUTBOX_POLL_SECONDS", "60"))
        prefix = options["prefix"]
        limit = options["limit"]
        while True:
            stats = flush_pending_email_dispatches(template_prefix=prefix or "", limit=limit)
            if stats["attempted"]:
                self.stdout.write(
                    f"email_outbox attempted={stats['attempted']} "
                    f"sent={stats['sent']} failed={stats['failed']}"
                )
            if options["once"]:
                return
            time.sleep(max(interval, 15))
