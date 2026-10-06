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
from apps.residents.models import AccessLevel, CompanyStatus, ResidentCompany, ResidentEmployee

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


def access_level_from_axtrax(
    *,
    has_turn_back: bool | None = None,
    access_group_name: str = "",
) -> str:
    """Map AxTrax access group → ERP level.

    Level 2 = arxa turniket (turn_back / Back readers) icazəli;
    Level 1 = yox.
    """
    if has_turn_back is True:
        return AccessLevel.LEVEL_2
    if has_turn_back is False:
        return AccessLevel.LEVEL_1
    name = (access_group_name or "").casefold()
    if "back" in name:
        return AccessLevel.LEVEL_2
    return AccessLevel.LEVEL_1


def _build_access_group_lookup(payload: dict) -> dict[int, dict]:
    """id → {name, has_turn_back} from export `access_groups` list."""
    lookup: dict[int, dict] = {}
    for raw in payload.get("access_groups") or []:
        try:
            gid = int(raw.get("id") or raw.get("access_group_id"))
        except (TypeError, ValueError):
            continue
        name = (raw.get("name") or raw.get("access_group_name") or "").strip()
        has_tb = raw.get("has_turn_back")
        if has_tb is None:
            has_tb = "back" in name.casefold()
        else:
            has_tb = bool(has_tb)
        lookup[gid] = {"name": name, "has_turn_back": has_tb}
    return lookup


def resolve_access_level_for_row(row: dict, group_lookup: dict[int, dict] | None = None) -> str | None:
    """Return AccessLevel value when export carries enough group info; else None."""
    if "has_turn_back" in row and row.get("has_turn_back") is not None:
        return access_level_from_axtrax(has_turn_back=bool(row.get("has_turn_back")))
    name = (row.get("access_group_name") or "").strip()
    if name:
        return access_level_from_axtrax(access_group_name=name)
    gid_raw = row.get("access_group_id")
    if gid_raw is None or group_lookup is None:
        return None
    try:
        gid = int(gid_raw)
    except (TypeError, ValueError):
        return None
    meta = group_lookup.get(gid)
    if not meta:
        return None
    return access_level_from_axtrax(
        has_turn_back=meta.get("has_turn_back"),
        access_group_name=meta.get("name") or "",
    )


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
                "access_group_id": row.get("access_group_id"),
                "access_group_name": row.get("access_group_name") or "",
                "has_turn_back": row.get("has_turn_back"),
            },
        )
        # Always prefer the latest non-empty AxTrax fields (card reassignment / renames).
        if row.get("identification"):
            emp["identification"] = row.get("identification") or ""
        if row.get("first_name"):
            emp["first_name"] = row.get("first_name") or ""
        if row.get("middle_name") is not None and str(row.get("middle_name") or ""):
            emp["middle_name"] = row.get("middle_name") or ""
        if row.get("last_name"):
            emp["last_name"] = row.get("last_name") or ""
        emp["is_enabled"] = bool(row.get("is_enabled", emp.get("is_enabled", True)))
        if emp.get("access_group_id") is None and row.get("access_group_id") is not None:
            emp["access_group_id"] = row.get("access_group_id")
        if row.get("access_group_name"):
            emp["access_group_name"] = row.get("access_group_name") or ""
        if row.get("has_turn_back") is not None:
            emp["has_turn_back"] = row.get("has_turn_back")
        badge = resolve_badge_number(row)
        if badge:
            emp["badge_number"] = badge
        card = (row.get("card_code") or "").strip()
        if card:
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


def _normalize_person_name(name: str) -> str:
    return _MULTISPACE_RE.sub(" ", (name or "").strip().lower())


def _find_unlinked_employee_by_name(company: ResidentCompany, full_name: str):
    """Portal-created employees have no AxTrax ExternalIdentity yet — match by name."""
    ct = ContentType.objects.get_for_model(ResidentEmployee)
    linked_ids = ExternalIdentity.objects.filter(
        system=AXTRAX_SYSTEM,
        external_id__startswith="emp:",
        entity_type=ct,
        entity_id__in=ResidentEmployee.objects.filter(company=company).values_list("id", flat=True),
    ).values_list("entity_id", flat=True)
    target = _normalize_person_name(full_name)
    if not target:
        return None
    for emp in ResidentEmployee.objects.filter(company=company).exclude(pk__in=linked_ids):
        if _normalize_person_name(emp.full_name) == target:
            return emp
    return None


def _reclaim_card_number(owner: ResidentEmployee, badge: str, stats: dict) -> None:
    """Ensure only ``owner`` holds this printed badge in ERP."""
    badge = normalize_identification(badge)
    if not badge or not owner.pk:
        return
    others = ResidentEmployee.objects.filter(card_number=badge).exclude(pk=owner.pk)
    cleared = others.update(card_number="")
    if cleared:
        stats["cards_reclaimed"] = stats.get("cards_reclaimed", 0) + cleared


def _deactivate_employee(employee: ResidentEmployee, *, clear_card: bool = True) -> bool:
    """Soft-deactivate; clear badge so former staff cannot keep a reassigned card."""
    fields = []
    changed = False
    if employee.is_active:
        employee.is_active = False
        fields.append("is_active")
        changed = True
    if employee.deactivated_at is None:
        employee.deactivated_at = timezone.now()
        fields.append("deactivated_at")
        changed = True
    if clear_card and employee.card_number:
        employee.card_number = ""
        fields.append("card_number")
        changed = True
    if fields:
        employee.save(update_fields=fields)
    return changed


def _badge_owner_map(departments: dict[int, dict]) -> dict[str, int]:
    """Printed badge → winning AxTrax employee_id (prefer enabled, then higher emp id)."""
    candidates: dict[str, list[tuple[bool, int]]] = defaultdict(list)
    for dept in departments.values():
        for emp in dept["employees"].values():
            badge = normalize_identification(emp.get("badge_number") or "")
            if not badge:
                continue
            candidates[badge].append((bool(emp.get("is_enabled")), int(emp["employee_id"])))
    winners: dict[str, int] = {}
    for badge, items in candidates.items():
        items.sort(key=lambda t: (t[0], t[1]))
        winners[badge] = items[-1][1]
    return winners


def sync_people_from_payload(payload: dict) -> dict:
    """Apply an AxTrax people payload (file or live MSSQL) into ERP."""
    return _sync_people_payload(payload)


@transaction.atomic
def _sync_people_payload(payload: dict) -> dict:
    rows = payload.get("rows") or []
    departments = _group_rows(rows)
    group_lookup = _build_access_group_lookup(payload)
    badge_winners = _badge_owner_map(departments)

    stats = defaultdict(int)
    stats["departments_in_file"] = len(departments)
    stats["employee_rows_in_file"] = len(rows)
    stats["access_groups_in_file"] = len(group_lookup)

    seen_emp_ids: set[int] = set()

    for dept in departments.values():
        company, created = _resolve_company(dept["department_id"], dept["department_name"])
        stats["companies_created" if created else "companies_updated"] += 1
        _upsert_external(AXTRAX_SYSTEM, f"dept:{dept['department_id']}", company)
        PartyService.upsert_from_resident_company(company)

        for emp in dept["employees"].values():
            seen_emp_ids.add(emp["employee_id"])
            full_name = clean_person_name(emp["first_name"], emp["middle_name"], emp["last_name"])
            ext_emp = f"emp:{emp['employee_id']}"
            identity = ExternalIdentity.objects.filter(system=AXTRAX_SYSTEM, external_id=ext_emp).first()
            employee = None
            if identity:
                employee = ResidentEmployee.objects.filter(pk=identity.entity_id).first()

            level = resolve_access_level_for_row(emp, group_lookup)
            badge = normalize_identification(emp.get("badge_number") or "")
            # If another AxTrax person owns this badge in this export, do not keep it here.
            if badge and badge_winners.get(badge) != emp["employee_id"]:
                badge = ""
                stats["badge_conflicts_skipped"] += 1

            now_active = bool(emp["is_enabled"])

            if employee:
                employee.company = company
                employee.full_name = full_name
                if employee.card_number != badge:
                    employee.card_number = badge
                    stats["cards_updated"] += 1
                was_active = employee.is_active
                employee.is_active = now_active
                if now_active and not was_active:
                    employee.deactivated_at = None
                elif (not now_active) and was_active and employee.deactivated_at is None:
                    employee.deactivated_at = timezone.now()
                if not now_active and employee.card_number:
                    employee.card_number = ""
                    stats["cards_cleared_inactive"] += 1
                if level is not None and employee.access_level != level:
                    employee.access_level = level
                    stats["access_levels_updated"] += 1
                employee.save()
                stats["employees_updated"] += 1
            else:
                employee = _find_unlinked_employee_by_name(company, full_name)
                if employee:
                    employee.company = company
                    employee.full_name = full_name
                    if employee.card_number != badge:
                        employee.card_number = badge
                        stats["cards_updated"] += 1
                    employee.is_active = now_active
                    if employee.is_active:
                        employee.deactivated_at = None
                    elif employee.deactivated_at is None:
                        employee.deactivated_at = timezone.now()
                    if not now_active and employee.card_number:
                        employee.card_number = ""
                        stats["cards_cleared_inactive"] += 1
                    if level is not None and employee.access_level != level:
                        employee.access_level = level
                        stats["access_levels_updated"] += 1
                    employee.save()
                    stats["employees_matched"] += 1
                else:
                    employee = ResidentEmployee.objects.create(
                        company=company,
                        full_name=full_name,
                        card_number=badge if now_active else "",
                        access_level=level or AccessLevel.LEVEL_1,
                        is_active=now_active,
                        deactivated_at=None if now_active else timezone.now(),
                    )
                    if level is not None:
                        stats["access_levels_updated"] += 1
                    stats["employees_created"] += 1

            if badge and now_active:
                _reclaim_card_number(employee, badge, stats)

            _upsert_external(AXTRAX_SYSTEM, ext_emp, employee)
            PartyService.upsert_person_from_employee(employee)

    # Soft-deactivate all AxTrax-linked employees missing from the full export (any company).
    ct = ContentType.objects.get_for_model(ResidentEmployee)
    linked = ExternalIdentity.objects.filter(
        system=AXTRAX_SYSTEM,
        external_id__startswith="emp:",
        entity_type=ct,
    )
    for ident in linked:
        try:
            ax_id = int(str(ident.external_id).split(":", 1)[1])
        except (IndexError, ValueError):
            continue
        if ax_id in seen_emp_ids:
            continue
        employee = ResidentEmployee.objects.filter(pk=ident.entity_id).first()
        if not employee:
            continue
        if _deactivate_employee(employee, clear_card=True):
            stats["employees_deactivated"] += 1

    SyncLog.objects.create(
        system=AXTRAX_SYSTEM,
        operation="sync_people",
        status=SyncStatus.SUCCESS,
        request_payload={"row_count": payload.get("row_count"), "source": payload.get("source")},
        response_payload=dict(stats),
    )
    return dict(stats)


def sync_people_from_export(path: Path) -> dict:
    return _sync_people_payload(load_export(path))


def sync_people_from_mssql() -> dict:
    from apps.integrations.axtrax_mssql import fetch_people_payload

    return _sync_people_payload(fetch_people_payload())
