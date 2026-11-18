"""Drain pending NotificationDispatch EMAIL rows (ticket.* and others)."""

from django.core.management.base import BaseCommand

from apps.comms.services import flush_pending_email_dispatches


class Command(BaseCommand):
    help = "Flush pending email NotificationDispatch rows (default: ticket.*)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--prefix",
            default="ticket.",
            help="template_code prefix (default ticket.). Empty = all pending email.",
        )
        parser.add_argument("--limit", type=int, default=50)

    def handle(self, *args, **options):
        prefix = options["prefix"]
        stats = flush_pending_email_dispatches(
            template_prefix=prefix or "",
            limit=options["limit"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "email_outbox "
                f"attempted={stats['attempted']} sent={stats['sent']} "
                f"failed={stats['failed']} retried={stats.get('retried', 0)}"
            )
        )
