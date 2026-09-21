from django.core.management.base import BaseCommand

from apps.accounts.invite import retry_failed_invite_dispatches


class Command(BaseCommand):
    help = "Retry failed portal invite emails (NotificationDispatch portal.invite)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        stats = retry_failed_invite_dispatches(limit=options["limit"])
        self.stdout.write(
            f"attempted={stats['attempted']} sent={stats['sent']} failed={stats['failed']}"
        )
