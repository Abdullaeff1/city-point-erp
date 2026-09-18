"""Export AccessEvent archive for a calendar year (AxTrax-independent backup)."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.residents.models import AccessEvent


class Command(BaseCommand):
    help = (
        "İllik giriş/çıxış arxivi (JSONL və ya CSV). "
        "AxTrax-da işçi silinsə belə ERP-dəki AccessEvent qalır; bu əmri ilə fayl backup da götürün."
    )

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Calendar year, e.g. 2025")
        parser.add_argument(
            "--out",
            type=str,
            default="",
            help="Output path (default: var/archive/access_YYYY.jsonl)",
        )
        parser.add_argument(
            "--format",
            choices=("jsonl", "csv"),
            default="jsonl",
            dest="fmt",
        )
        parser.add_argument(
            "--company",
            type=str,
            default="",
            help="Optional company slug filter",
        )

    def handle(self, *args, **options):
        year = int(options["year"])
        if year < 2000 or year > 2100:
            raise CommandError("year out of range")

        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime(year, 1, 1, 0, 0, 0), tz)
        end = timezone.make_aware(datetime(year + 1, 1, 1, 0, 0, 0), tz)

        qs = (
            AccessEvent.objects.filter(occurred_at__gte=start, occurred_at__lt=end)
            .select_related("employee", "employee__company")
            .order_by("occurred_at", "id")
        )
        company_slug = (options.get("company") or "").strip()
        if company_slug:
            qs = qs.filter(employee__company__slug=company_slug)

        out = (options.get("out") or "").strip()
        fmt = options["fmt"]
        if not out:
            suffix = "csv" if fmt == "csv" else "jsonl"
            slug_part = f"_{company_slug}" if company_slug else ""
            out = f"var/archive/access_{year}{slug_part}.{suffix}"

        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)

        count = 0
        if fmt == "csv":
            with path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(
                    fh,
                    fieldnames=[
                        "occurred_at",
                        "event_type",
                        "employee_name",
                        "card_number",
                        "axtrax_employee_id",
                        "company",
                        "employee_id",
                        "is_active",
                        "deactivated_at",
                    ],
                )
                writer.writeheader()
                for e in qs.iterator(chunk_size=2000):
                    writer.writerow(self._row(e))
                    count += 1
        else:
            with path.open("w", encoding="utf-8") as fh:
                for e in qs.iterator(chunk_size=2000):
                    fh.write(json.dumps(self._row(e), ensure_ascii=False, default=str) + "\n")
                    count += 1

        self.stdout.write(self.style.SUCCESS(f"Exported {count} events → {path}"))

    def _row(self, e: AccessEvent) -> dict:
        emp = e.employee
        return {
            "occurred_at": timezone.localtime(e.occurred_at).isoformat(),
            "event_type": e.event_type,
            "employee_name": e.employee_name or emp.full_name,
            "card_number": e.card_number or emp.card_number,
            "axtrax_employee_id": e.axtrax_employee_id,
            "company": emp.company.name if emp.company_id else "",
            "employee_id": emp.pk,
            "is_active": emp.is_active,
            "deactivated_at": (
                timezone.localtime(emp.deactivated_at).isoformat() if emp.deactivated_at else ""
            ),
        }
