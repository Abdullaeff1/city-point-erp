"""Reassign AccessEvent FKs so punch snapshot name/card/company match the right person."""

from django.core.management.base import BaseCommand

from apps.integrations.access_event_rematch import rematch_access_events


class Command(BaseCommand):
    help = (
        "AccessEvent.employee FK-ni snapshot adda (employee_name) uyğun işçiyə köçürür; "
        "tapılmayan keçmiş işçilər üçün arxiv (is_active=False) qeyd yaradır."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Heç nə yazma; yalnız statistika göstər",
        )
        parser.add_argument(
            "--no-create",
            action="store_true",
            help="Tapılmayan adlar üçün arxiv işçi yaratma",
        )

    def handle(self, *args, **options):
        stats = rematch_access_events(
            dry_run=bool(options["dry_run"]),
            create_missing=not bool(options["no_create"]),
        )
        self.stdout.write(self.style.SUCCESS(str(stats)))
