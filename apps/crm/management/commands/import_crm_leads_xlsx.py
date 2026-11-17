"""Import office leads from «Yeni müştəri sorğuları» Excel (Ümumi + Pərvanə)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from openpyxl import load_workbook

from apps.crm.mapping import (
    infer_outcome_from_notes,
    map_outcome,
    map_pipeline_stage,
    map_record_status,
    map_source,
    parse_area_range,
)
from apps.crm.models import (
    ActivityType,
    Lead,
    LeadActivity,
    LeadStatus,
    PipelineStage,
    Qualification,
    RecordStatus,
)

DEFAULT_PATH = Path("docs/data/yeni_musteri_sorgulari_v2.xlsx")
DEFAULT_SHEETS = ("Ümumi müştərilər", "Pərvanə x müştəriləri")
SKIP_SHEET_HINTS = ("meeting room", "meeting")

HEADER_ALIASES = {
    "şirkət adı": "company_name",
    "əlaqəli şəxs": "full_name",
    "əlaqə nöm": "phone",
    "əlaqə nömrəsi": "phone",
    "müraciət tarixi": "inquired_at",
    "lid mənbəyi": "source",
    "tələb olunan sahə": "area_wanted",
    "seçim edilən sahə": "area_offered",
    "təklif edilən sahə": "area_offered",
    "qiymət": "price",
    "qiymət ": "price",
    "lid statusu": "pipeline_stage",
    "nəticə": "outcome",
    "sorğu statusu": "record_status",
    "qeydlər": "notes",
    "№": "row_no",
    "no": "row_no",
}


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    return str(v).strip()


def _norm_header(v) -> str:
    return " ".join(_cell(v).lower().split())


def _parse_date(raw: str):
    text = (raw or "").strip()
    if not text or text in {"-", "—"}:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    d = parse_date(text[:10]) if len(text) >= 10 and text[4] == "-" else None
    if d:
        return d
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:16].split()[0], fmt).date()
        except ValueError:
            continue
    return None


def _slug_sheet(name: str) -> str:
    # ASCII-stable id (Ümumi müştərilər → umumi-musteriler)
    trans = str.maketrans(
        {
            "ə": "e",
            "Ə": "e",
            "ı": "i",
            "İ": "i",
            "ö": "o",
            "Ö": "o",
            "ü": "u",
            "Ü": "u",
            "ğ": "g",
            "Ğ": "g",
            "ş": "s",
            "Ş": "s",
            "ç": "c",
            "Ç": "c",
        }
    )
    s = (name or "").strip().lower().translate(trans)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:48] or "sheet"


def _find_header_row(rows: list) -> tuple[int, dict[str, int]] | None:
    for idx, row in enumerate(rows[:25]):
        mapping: dict[str, int] = {}
        for col, val in enumerate(row):
            key = _norm_header(val)
            if not key:
                continue
            field = HEADER_ALIASES.get(key)
            if field:
                mapping[field] = col
        if "company_name" in mapping and "phone" in mapping:
            return idx, mapping
    return None


def _get(row, cols: dict[str, int], field: str) -> str:
    i = cols.get(field)
    if i is None or i >= len(row):
        return ""
    return _cell(row[i])


class Command(BaseCommand):
    help = (
        "Import CRM leads from Yeni müştəri sorğuları xlsx "
        "(Ümumi + Pərvanə; Meeting Room / aylıq sheet-lər atlanır)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default=str(DEFAULT_PATH),
            help="Path to xlsx (default docs/data/yeni_musteri_sorgulari_v2.xlsx)",
        )
        parser.add_argument(
            "--sheet",
            action="append",
            dest="sheets",
            help="Sheet name to import (repeatable). Default: Ümumi + Pərvanə.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write to DB (default is dry-run).",
        )
        parser.add_argument("--limit", type=int, default=0, help="Max rows per sheet (0=all).")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"Fayl tapılmadı: {path}")
        apply = bool(options["apply"])
        limit = int(options["limit"] or 0)
        wanted = options["sheets"] or list(DEFAULT_SHEETS)

        wb = load_workbook(path, data_only=True, read_only=True)
        stats = {"sheets": 0, "rows": 0, "created": 0, "updated": 0, "skipped": 0}

        for sheet_name in wb.sheetnames:
            if sheet_name.strip() not in {s.strip() for s in wanted}:
                continue
            low = sheet_name.strip().lower()
            if any(h in low for h in SKIP_SHEET_HINTS):
                self.stdout.write(self.style.WARNING(f"Skip Meeting Room sheet: {sheet_name}"))
                continue
            ws = wb[sheet_name]
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            found = _find_header_row(rows)
            if not found:
                self.stdout.write(self.style.WARNING(f"Header yoxdur: {sheet_name}"))
                continue
            header_idx, cols = found
            stats["sheets"] += 1
            slug = _slug_sheet(sheet_name)
            processed = 0
            for row in rows[header_idx + 1 :]:
                if limit and processed >= limit:
                    break
                company = _get(row, cols, "company_name")
                full_name = _get(row, cols, "full_name")
                phone = _get(row, cols, "phone")
                notes = _get(row, cols, "notes")
                row_no = _get(row, cols, "row_no") or str(processed + 1)
                if not any([(company not in {"", "-"}), (full_name not in {"", "-"}), (phone not in {"", "-"})]):
                    stats["skipped"] += 1
                    continue
                if company in {"", "-"} and full_name in {"", "-"} and phone in {"", "-"}:
                    stats["skipped"] += 1
                    continue

                source_raw = _get(row, cols, "source")
                source, source_note = map_source(source_raw)
                stage = map_pipeline_stage(_get(row, cols, "pipeline_stage"))
                record = map_record_status(_get(row, cols, "record_status"))
                outcome = map_outcome(_get(row, cols, "outcome"))
                outcome = infer_outcome_from_notes(notes, existing=outcome)
                inquired = _parse_date(_get(row, cols, "inquired_at"))
                min_a, max_a, area_note = parse_area_range(_get(row, cols, "area_wanted"))
                offered = _get(row, cols, "area_offered")
                price = _get(row, cols, "price")
                initial_parts = [p for p in (area_note if area_note != _get(row, cols, "area_wanted") else "", offered, price) if p and p not in {"-", "—"}]
                # Keep area wanted text in initial_note when useful
                if _get(row, cols, "area_wanted") and _get(row, cols, "area_wanted") not in {"-", "—"}:
                    if _get(row, cols, "area_wanted") not in initial_parts:
                        initial_parts.insert(0, f"Tələb: {_get(row, cols, 'area_wanted')}")
                if offered and offered not in {"-", "—"}:
                    initial_parts.append(f"Təklif/seçim: {offered}")
                if price and price not in {"-", "—"}:
                    initial_parts.append(f"Qiymət: {price}")
                # dedupe parts
                seen = set()
                initial_note = "; ".join(x for x in initial_parts if not (x in seen or seen.add(x)))[:2000]

                external_id = f"xlsx:{slug}:{row_no}"
                stats["rows"] += 1
                processed += 1

                if not apply:
                    continue

                with transaction.atomic():
                    lead = Lead.objects.filter(external_id=external_id).first()
                    created = lead is None
                    if lead is None:
                        lead = Lead(external_id=external_id)
                    lead.company_name = (company if company not in {"-", "—"} else "")[:200]
                    lead.full_name = (full_name if full_name not in {"-", "—"} else "")[:200]
                    lead.phone = (phone if phone not in {"-", "—"} else "")[:64]
                    lead.source = source
                    lead.source_note = source_note
                    lead.inquired_at = inquired
                    lead.min_area_m2 = min_a
                    lead.max_area_m2 = max_a
                    lead.pipeline_stage = stage
                    lead.record_status = record
                    if outcome:
                        lead.outcome = outcome
                    lead.message = (notes or "")[:5000]
                    lead.initial_note = initial_note
                    if record == RecordStatus.CLOSED and stage not in (
                        PipelineStage.WON,
                        PipelineStage.LOST,
                        PipelineStage.ON_HOLD,
                    ):
                        if outcome == "cooperation_secured":
                            lead.pipeline_stage = PipelineStage.WON
                            lead.qualification = Qualification.POTENTIAL
                            lead.status = LeadStatus.CONVERTED
                        else:
                            lead.pipeline_stage = PipelineStage.LOST
                            if not lead.qualification or lead.qualification == Qualification.UNREVIEWED:
                                lead.qualification = Qualification.NON_POTENTIAL
                                lead.status = LeadStatus.DISQUALIFIED
                    elif stage == PipelineStage.WON:
                        lead.qualification = Qualification.POTENTIAL
                        lead.status = LeadStatus.CONVERTED
                    elif lead.qualification == Qualification.UNREVIEWED and stage not in (
                        PipelineStage.WORKING,
                        PipelineStage.CONTACT_PENDING,
                    ):
                        lead.qualification = Qualification.POTENTIAL
                        lead.status = LeadStatus.QUALIFIED
                    if not lead.company_name and not lead.full_name and not lead.phone and not lead.email:
                        lead.contact_missing_reason = "Excel sətirində əlaqə boş"
                    lead.full_clean()
                    lead.save()
                    if notes and not LeadActivity.objects.filter(
                        lead=lead, activity_type=ActivityType.NOTE, body=notes[:2000]
                    ).exists():
                        LeadActivity.objects.create(
                            lead=lead,
                            activity_type=ActivityType.NOTE,
                            body=notes[:5000],
                            occurred_at=timezone.now(),
                        )
                    if created:
                        stats["created"] += 1
                    else:
                        stats["updated"] += 1

        mode = "APPLY" if apply else "DRY-RUN"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] sheets={stats['sheets']} rows={stats['rows']} "
                f"created={stats['created']} updated={stats['updated']} skipped={stats['skipped']}"
            )
        )
        if not apply:
            self.stdout.write("Yazmaq üçün --apply əlavə edin.")
