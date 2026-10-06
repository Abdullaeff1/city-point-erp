from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.axtrax_people_sync import sync_people_from_export, sync_people_from_mssql


class Command(BaseCommand):
    help = "AxTraxNG people → ResidentCompany / ResidentEmployee (JSON export və ya live MSSQL)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default="var/axtrax_people.json",
            help="Path to axtrax_people.json export (default: var/axtrax_people.json)",
        )
        parser.add_argument(
            "--from-mssql",
            action="store_true",
            help="Pull latest people/cards live from AxTrax MS SQL (ignores --file)",
        )

    def handle(self, *args, **options):
        if options["from_mssql"]:
            stats = sync_people_from_mssql()
            self.stdout.write(self.style.SUCCESS("AxTrax people sync (live MSSQL) tamamlandı."))
        else:
            path = Path(options["file"])
            if not path.is_absolute():
                path = Path.cwd() / path
            if not path.exists():
                raise CommandError(f"Export file not found: {path}")
            stats = sync_people_from_export(path)
            self.stdout.write(self.style.SUCCESS("AxTrax people sync tamamlandı."))
        for key, value in sorted(stats.items()):
            self.stdout.write(f"  {key}: {value}")
