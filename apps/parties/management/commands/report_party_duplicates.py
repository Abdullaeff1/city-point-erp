"""Dry-run report of Party / Resident* duplicates (no merge)."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.parties.dedupe import build_duplicate_report


class Command(BaseCommand):
    help = "Report duplicate companies/parties/people (read-only; no merge)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print full report as JSON.",
        )

    def handle(self, *args, **options):
        report = build_duplicate_report()
        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            return

        sections = [
            ("company_voen", "Eyni VÖEN — ResidentCompany"),
            ("party_tax_id", "Eyni tax_id — Party"),
            ("company_name", "Eyni ad (zəif) — Company"),
            ("party_name", "Eyni ad (zəif) — Party"),
            ("companies_missing_party", "Company without Party bridge"),
            ("orphan_resident_parties", "Orphan resident-like Party"),
            ("employee_name", "Eyni ad + company — Employee"),
        ]
        total = 0
        for key, title in sections:
            rows = report.get(key) or []
            total += len(rows)
            self.stdout.write(self.style.NOTICE(f"\n=== {title}: {len(rows)} ==="))
            for row in rows[:50]:
                self.stdout.write(f"  {row}")
            if len(rows) > 50:
                self.stdout.write(f"  ... +{len(rows) - 50} more")
        self.stdout.write(self.style.SUCCESS(f"\nTotal finding groups/rows: {total}"))
        self.stdout.write("Merge yox — qayda: docs/architecture/m1-party-resident-mapping.md §2")
