from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.axtrax_events_sync import get_events_cursor, sync_events_from_export


class Command(BaseCommand):
    help = "AxTraxNG events JSON → AccessEvent (qısa poll üçün təkrar çağırın)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default="var/axtrax_events.json",
            help="Path to axtrax_events.json (default: var/axtrax_events.json)",
        )
        parser.add_argument(
            "--since-id",
            type=int,
            default=None,
            help="Override cursor (default: last saved IdAutoEvents)",
        )
        parser.add_argument(
            "--show-cursor",
            action="store_true",
            help="Print current events cursor and exit",
        )

    def handle(self, *args, **options):
        if options["show_cursor"]:
            self.stdout.write(f"events_cursor={get_events_cursor()}")
            return
        path = Path(options["file"])
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise CommandError(f"Export file not found: {path}")
        stats = sync_events_from_export(path, since_id=options["since_id"])
        self.stdout.write(self.style.SUCCESS("AxTrax events sync tamamlandı."))
        for key, value in sorted(stats.items()):
            self.stdout.write(f"  {key}: {value}")
