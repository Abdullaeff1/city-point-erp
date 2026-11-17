"""Party / Resident* duplicate detection — report only, no merge."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from django.db.models import Count, Q

from apps.parties.models import Party
from apps.residents.models import ResidentCompany, ResidentEmployee


def normalize_tax_id(value: str | None) -> str:
    raw = (value or "").strip().upper()
    return re.sub(r"[^0-9A-Z]", "", raw)


def normalize_name(value: str | None) -> str:
    raw = (value or "").strip().lower()
    raw = re.sub(r"\s+", " ", raw)
    return raw


def find_duplicate_companies_by_voen() -> list[dict[str, Any]]:
    groups: dict[str, list[ResidentCompany]] = defaultdict(list)
    for company in ResidentCompany.objects.all().only("id", "name", "voen", "slug", "is_archived", "status"):
        key = normalize_tax_id(company.voen)
        if not key:
            continue
        groups[key].append(company)
    return [
        {
            "key": key,
            "kind": "company_voen",
            "ids": [c.pk for c in rows],
            "names": [c.name for c in rows],
        }
        for key, rows in sorted(groups.items())
        if len(rows) > 1
    ]


def find_duplicate_parties_by_tax_id() -> list[dict[str, Any]]:
    groups: dict[str, list[Party]] = defaultdict(list)
    for party in Party.objects.all().only("id", "legal_name", "tax_id", "status", "legacy_resident_company_id"):
        key = normalize_tax_id(party.tax_id)
        if not key:
            continue
        groups[key].append(party)
    return [
        {
            "key": key,
            "kind": "party_tax_id",
            "ids": [p.pk for p in rows],
            "names": [p.legal_name for p in rows],
            "legacy_company_ids": [p.legacy_resident_company_id for p in rows],
        }
        for key, rows in sorted(groups.items())
        if len(rows) > 1
    ]


def find_duplicate_names_weak(*, model: str = "company") -> list[dict[str, Any]]:
    """Same normalized name, different tax ids — manual review."""
    groups: dict[str, list[Any]] = defaultdict(list)
    if model == "party":
        qs = Party.objects.all().only("id", "legal_name", "tax_id")
        name_attr, tax_attr = "legal_name", "tax_id"
    else:
        qs = ResidentCompany.objects.all().only("id", "name", "voen")
        name_attr, tax_attr = "name", "voen"
    for row in qs:
        nkey = normalize_name(getattr(row, name_attr))
        if not nkey:
            continue
        groups[nkey].append(row)
    out: list[dict[str, Any]] = []
    for nkey, rows in sorted(groups.items()):
        if len(rows) < 2:
            continue
        taxes = {normalize_tax_id(getattr(r, tax_attr)) for r in rows}
        taxes.discard("")
        if len(taxes) <= 1 and len(rows) == len(taxes or {""}):
            # identical tax or all empty with same name still flag if >1 row
            pass
        out.append(
            {
                "key": nkey,
                "kind": f"{model}_name",
                "ids": [r.pk for r in rows],
                "tax_ids": [getattr(r, tax_attr) for r in rows],
            }
        )
    return out


def find_companies_missing_party() -> list[dict[str, Any]]:
    linked_ids = set(
        Party.objects.exclude(legacy_resident_company_id=None).values_list(
            "legacy_resident_company_id", flat=True
        )
    )
    rows = (
        ResidentCompany.objects.exclude(pk__in=linked_ids)
        .only("id", "name", "voen", "slug")
        .order_by("name")
    )
    return [{"id": c.pk, "name": c.name, "voen": c.voen, "slug": c.slug} for c in rows]


def find_orphan_resident_parties() -> list[dict[str, Any]]:
    """Parties with no legacy company that look like residents (have leases or RESIDENT role)."""
    qs = (
        Party.objects.filter(legacy_resident_company__isnull=True)
        .annotate(
            lease_n=Count("leases", distinct=True),
            role_n=Count("roles", filter=Q(roles__role="resident"), distinct=True),
        )
        .filter(Q(lease_n__gt=0) | Q(role_n__gt=0))
        .only("id", "legal_name", "tax_id", "status")
    )
    return [
        {
            "id": p.pk,
            "name": p.legal_name,
            "tax_id": p.tax_id,
            "status": p.status,
            "leases": p.lease_n,
            "resident_role": p.role_n > 0,
        }
        for p in qs
    ]


def find_duplicate_employees_by_name() -> list[dict[str, Any]]:
    groups: dict[tuple[int | None, str], list[ResidentEmployee]] = defaultdict(list)
    for emp in ResidentEmployee.objects.filter(is_active=True).only("id", "full_name", "company_id"):
        nkey = normalize_name(emp.full_name)
        if not nkey or not emp.company_id:
            continue
        groups[(emp.company_id, nkey)].append(emp)
    return [
        {
            "key": f"company={cid}:{nkey}",
            "kind": "employee_name",
            "company_id": cid,
            "ids": [e.pk for e in rows],
            "names": [e.full_name for e in rows],
        }
        for (cid, nkey), rows in sorted(groups.items())
        if len(rows) > 1
    ]


def build_duplicate_report() -> dict[str, Any]:
    return {
        "company_voen": find_duplicate_companies_by_voen(),
        "party_tax_id": find_duplicate_parties_by_tax_id(),
        "company_name": find_duplicate_names_weak(model="company"),
        "party_name": find_duplicate_names_weak(model="party"),
        "companies_missing_party": find_companies_missing_party(),
        "orphan_resident_parties": find_orphan_resident_parties(),
        "employee_name": find_duplicate_employees_by_name(),
    }
