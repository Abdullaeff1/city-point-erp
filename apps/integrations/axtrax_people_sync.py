"""Import AxTraxNG people export into ResidentCompany / ResidentEmployee."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.integrations.models import ExternalIdentity, SyncLog, SyncStatus
from apps.parties.services import PartyService
from apps.residents.models import CompanyStatus, ResidentCompany, ResidentEmployee

AXTRAX_SYSTEM = "axtraxng"

# Known AxTrax department labels → stable ERP slugs (especially ASBC).
DEPARTMENT_SLUG_ALIASES = {
    "asbc": "asbc",
    "techco": "techco",
    "city point": "city-point",
}

# Operator / landlord departments — not tenant residents
INTERNAL_COMPANY_SLUGS = {"city-point"}

_CARD_NOISE_RE = re.compile(
    r"(\b\d{3}\s?\d{3}\b|\bcard\s*\d+\b|\(\s*card[^)]*\)|\b0{5,}\d+\b)",
    re.IGNORECASE,
)
_MULTISPACE_RE = re.compile(r"\s+")
# Real badge / identification printed on cards, e.g. 005444, 004 852, 000301
_IDENT_IN_NAME_RE = re.compile(r"\b(\d{3}\s?\d{3}|\d{5,8})\b")


def normalize_identification(value: str) -> str:
    """Keep digits only so '004 852' → '004852'."""
    digits = re.sub(r"\D", "", value or "")
    return digits[:32]


def extract_identification_from_name(*parts: str) -> str:
    for part in parts:
        match = _IDENT_IN_NAME_RE.search(part or "")
        if match:
            return normalize_identification(match.group(1))
    return ""


def resolve_badge_number(row: dict) -> str:
    """Prefer AxTrax tIdentification; else number next to name; never internal iCardCode."""
    ident = normalize_identification(row.get("identification") or "")
    if ident:
        return ident
    from_name = extract_identification_from_name(
        row.get("first_name") or "",
        row.get("middle_name") or "",
        row.get("last_name") or "",
    )
    return from_name


def clean_person_name(first_name: str, middle_name: str, last_name: str) -> str:
    parts = []
    for raw in (first_name or "", middle_name or "", last_name or ""):
        cleaned = _CARD_NOISE_RE.sub(" ", raw)
        cleaned = _MULTISPACE_RE.sub(" ", cleaned).strip(" ,.-")
        if cleaned:
            parts.append(cleaned)
    return " ".join(parts)[:160] or "Unknown"


def normalize_dept_key(name: str) -> str:
    return _MULTISPACE_RE.sub(" ", (name or "").strip().lower())


def company_slug_for_department(department_id: int, department_name: str) -> str:
    key = normalize_dept_key(department_name)
    if key in DEPARTMENT_SLUG_ALIASES:
        return DEPARTMENT_SLUG_ALIASES[key]
    base = slugify(department_name) or f"dept-{department_id}"
    # Keep ASCII slug short and stable with AxTrax id suffix when generic.
    if base in {"asbc", "techco"}:
        return base
    return f"{base[:40]}-ax{department_id}"


def load_export(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _group_rows(rows: list[dict]) -> dict[int, dict]:
    """department_id → {name, employees: {emp_id → payload}}."""
    departments: dict[int, dict] = {}
    for row in rows:
        dept_id = int(row["department_id"])
        emp_id = int(row["employee_id"])
        dept = departments.setdefault(
            dept_id,
            {"department_id": dept_id, "department_name": row["department_name"], "employees": {}},
        )
        emp = dept["employees"].setdefault(
            emp_id,
            {
                "employee_id": emp_id,
                "first_name": row.get("first_name") or "",
                "middle_name": row.get("middle_name") or "",
                "last_name": row.get("last_name") or "",
                "email": row.get("email") or "",
                "mobile": row.get("mobile") or "",
                "identification": row.get("identification") or "",
                "is_enabled": bool(row.get("is_enabled", True)),
                "badge_number": "",
                "card_code": "",
            },
        )
        if not emp.get("identification") and row.get("identification"):
            emp["identification"] = row.get("identification") or ""
        badge = resolve_badge_number(row)
        if badge and not emp["badge_number"]:
            emp["badge_number"] = badge
        card = (row.get("card_code") or "").strip()
        if card and not emp["card_code"]:
            emp["card_code"] = card[:32]
    return departments


def _upsert_external(system: str, external_id: str, obj) -> ExternalIdentity:
    ct = ContentType.objects.get_for_model(obj.__class__)
    identity, _ = ExternalIdentity.objects.update_or_create(
        system=system,
        external_id=str(external_id),
        defaults={
            "entity_type": ct,
            "entity_id": obj.pk,
            "last_sync_at": timezone.now(),
            "last_status": SyncStatus.SUCCESS,
            "last_error": "",
        },
    )
    return identity


def _apply_company_flags(company: ResidentCompany, slug: str) -> list[str]:
    """Mark City Point (operator) as internal — not a tenant resident."""
    fields = []
    internal = slug in INTERNAL_COMPANY_SLUGS
    if company.is_internal != internal:
        company.is_internal = internal
        fields.append("is_internal")
    if internal and company.portal_active:
        company.portal_active = False
        fields.append("portal_active")
    return fields


def _resolve_company(department_id: int, department_name: str) -> tuple[ResidentCompany, bool]:
    """Find existing company by AxTrax identity, alias slug, or create."""
    ext_id = f"dept:{department_id}"
    existing = ExternalIdentity.objects.filter(system=AXTRAX_SYSTEM, external_id=ext_id).first()
    if existing and existing.entity_id:
        company = ResidentCompany.objects.filter(pk=existing.entity_id).first()
        if company:
            company.name = department_name[:160]
            company.status = CompanyStatus.ACTIVE
            fields = ["name", "status"]
            fields.extend(_apply_company_flags(company, company.slug))
            company.save(update_fields=list(dict.fromkeys(fields)))
            _upsert_external(AXTRAX_SYSTEM, ext_id, company)
            PartyService.upsert_from_resident_company(company)
            return company, False

    slug = company_slug_for_department(department_id, department_name)
    company = ResidentCompany.objects.filter(slug=slug).first()
    created = False
    if not company and slug == "asbc":
        company = ResidentCompany.objects.filter(slug="asbc").first()
    if company:
        fields = []
        if company.name != department_name[:160]:
            company.name = department_name[:160]
            fields.append("name")
        fields.extend(_apply_company_flags(company, company.slug))
        if fields:
            company.save(update_fields=list(dict.fromkeys(fields)))
    else:
        internal = slug in INTERNAL_COMPANY_SLUGS
        company = ResidentCompany.objects.create(
            name=department_name[:160],
            slug=slug,
            status=CompanyStatus.ACTIVE,
            portal_active=(slug == "asbc") and not internal,
            is_internal=internal,
        )
        created = True
    _upsert_external(AXTRAX_SYSTEM, ext_id, company)
    PartyService.upsert_from_resident_company(company)
    return company, created


@transaction.atomic
def sync_people_from_export(path: Path) -> dict:
    payload = load_export(path)
    rows = payload.get("rows") or []
    departments = _group_rows(rows)

    stats = defaultdict(int)
    stats["departments_in_file"] = len(departments)
    stats["employee_rows_in_file"] = len(rows)

    for dept in departments.values():
        company, created = _resolve_company(dept["department_id"], dept["department_name"])
        stats["companies_created" if created else "companies_updated"] += 1
        _upsert_external(AXTRAX_SYSTEM, f"dept:{dept['department_id']}", company)
        PartyService.upsert_from_resident_company(company)

        seen_emp_ids = set()
        for emp in dept["employees"].values():
            seen_emp_ids.add(emp["employee_id"])
            full_name = clean_person_name(emp["first_name"], emp["middle_name"], emp["last_name"])
            ext_emp = f"emp:{emp['employee_id']}"
            identity = ExternalIdentity.objects.filter(system=AXTRAX_SYSTEM, external_id=ext_emp).first()
            employee = None
            if identity:
                employee = ResidentEmployee.objects.filter(pk=identity.entity_id).first()

            if employee:
                employee.company = company
                employee.full_name = full_name
                badge = emp.get("badge_number") or ""
                if badge:
                    employee.card_number = badge
                was_active = employee.is_active
                now_active = bool(emp["is_enabled"])
                employee.is_active = now_active
                if now_active and not was_active:
                    employee.deactivated_at = None
                elif (not now_active) and was_active and employee.deactivated_at is None:
                    employee.deactivated_at = timezone.now()
                employee.save()
                stats["employees_updated"] += 1
            else:
                employee = ResidentEmployee.objects.create(
                    company=company,
                    full_name=full_name,
                    card_number=emp.get("badge_number") or "",
                    is_active=bool(emp["is_enabled"]),
                    deactivated_at=None if emp["is_enabled"] else timezone.now(),
                )
                stats["employees_created"] += 1

            _upsert_external(AXTRAX_SYSTEM, ext_emp, employee)
            PartyService.upsert_person_from_employee(employee)

        # Soft-deactivate AxTrax-linked employees missing from this department export.
        # Never hard-delete — AccessEvent history must remain queryable.
        ct = ContentType.objects.get_for_model(ResidentEmployee)
        linked = ExternalIdentity.objects.filter(
            system=AXTRAX_SYSTEM,
            external_id__startswith="emp:",
            entity_type=ct,
            entity_id__in=ResidentEmployee.objects.filter(company=company).values_list("id", flat=True),
        )
        for ident in linked:
            try:
                ax_id = int(str(ident.external_id).split(":", 1)[1])
            except (IndexError, ValueError):
                continue
            if ax_id not in seen_emp_ids:
                qs = ResidentEmployee.objects.filter(pk=ident.entity_id, is_active=True)
                updated = qs.update(is_active=False, deactivated_at=timezone.now())
                # If already inactive but deactivated_at empty, stamp once
                if not updated:
                    ResidentEmployee.objects.filter(
                        pk=ident.entity_id, is_active=False, deactivated_at__isnull=True
                    ).update(deactivated_at=timezone.now())
                else:
                    stats["employees_deactivated"] += 1

    SyncLog.objects.create(
        system=AXTRAX_SYSTEM,
        operation="sync_people",
        status=SyncStatus.SUCCESS,
        request_payload={"path": str(path), "row_count": payload.get("row_count")},
        response_payload=dict(stats),
    )
    return dict(stats)
