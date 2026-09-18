from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.axtrax_people_sync import sync_people_from_export


class Command(BaseCommand):
    help = "AxTraxNG people JSON export → ResidentCompany / ResidentEmployee (ASBC daxil)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default="var/axtrax_people.json",
            help="Path to axtrax_people.json export (default: var/axtrax_people.json)",
        )

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise CommandError(f"Export file not found: {path}")
        stats = sync_people_from_export(path)
        self.stdout.write(self.style.SUCCESS("AxTrax people sync tamamlandı."))
        for key, value in sorted(stats.items()):
            self.stdout.write(f"  {key}: {value}")
