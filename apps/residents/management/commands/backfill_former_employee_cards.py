"""Köhnə əməkdaşların boş kart nömrəsini AccessEvent tarixçəsindən doldur."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.residents.former_cards import backfill_former_employee_cards


class Command(BaseCommand):
    help = (
        "Deaktiv işçilərin boş card_number sahəsini keçid tarixçəsindən bərpa edir; "
        "boş AccessEvent.card_number də eyni kartla doldurulur."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Yalnız hesabat (default, --apply yoxdursa).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Kart nömrələrini yaz (idempotent).",
        )

    def handle(self, *args, **options):
        apply = bool(options.get("apply"))
        stats = backfill_former_employee_cards(apply=apply)
        mode = "APPLY" if apply else "DRY-RUN"
        self.stdout.write(f"[{mode}] former_empty={stats['former_empty']}")
        self.stdout.write(f"[{mode}] inferred={stats['inferred']}")
        self.stdout.write(f"[{mode}] no_history={stats['no_history']}")
        self.stdout.write(f"[{mode}] already_had_card={stats['skipped_already_set']}")
        if apply:
            self.stdout.write(self.style.SUCCESS(
                f"employees_updated={stats['employees_updated']} "
                f"events_updated={stats['events_updated']}"
            ))
        else:
            self.stdout.write(
                f"employees_would_update={stats.get('employees_would_update', 0)} "
                f"events_would_update={stats.get('events_would_update', 0)}"
            )
            self.stdout.write("Yazmaq üçün: manage.py backfill_former_employee_cards --apply")
