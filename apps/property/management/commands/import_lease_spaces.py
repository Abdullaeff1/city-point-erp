from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.property.lease_space_import import apply_import, preview_import


class Command(BaseCommand):
    help = "Excel-dən icarə / boş sahələri Space + ResidentCompany ilə uyğunlaşdırır."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default="var/cp_icare_ve_bos_saheler.xlsx",
            help="Excel yolu (default: var/cp_icare_ve_bos_saheler.xlsx)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Yalnız önizləmə; DB dəyişmir.",
        )
        parser.add_argument(
            "--no-create-companies",
            action="store_true",
            help="Tapılmayan şirkətləri yaratma.",
        )

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"Fayl tapılmadı: {path}")

        if options["dry_run"]:
            rows = preview_import(path)
            self.stdout.write(f"Sətir: {len(rows)}")
            for r in rows:
                self.stdout.write(
                    f"{r['code']:12} F={r['floor_code']} {r['area_m2']:>8} m² "
                    f"{r['status_raw'][:20]:20} → {r['company'] or '—'} | {r['label']}"
                )
            linked = sum(1 for r in rows if r["company"])
            self.stdout.write(self.style.SUCCESS(f"Uyğun şirkət: {linked}/{len(rows)}"))
            return

        stats = apply_import(
            path,
            create_missing_companies=not options["no_create_companies"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "OK rows={rows} created={created} updated={updated} "
                "linked={linked} unmatched={unmatched_leased} floors={floors}".format(
                    **{**stats, "floors": ",".join(stats["floors"])}
                )
            )
        )
        if stats["created_companies"]:
            self.stdout.write("Yeni şirkətlər: " + ", ".join(stats["created_companies"]))
