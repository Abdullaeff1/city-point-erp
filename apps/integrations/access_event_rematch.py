"""Reassign AccessEvent rows whose snapshot name no longer matches the linked employee.

AxTrax reuses ``IdEmpNum`` for a new person; people-sync used to overwrite
``ResidentEmployee.full_name`` on the same row. Historical punches kept the old
snapshot name but stayed on the renamed FK — this rematch moves them to the
person (or archive stub) that matches ``employee_name``.
"""

from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone

from apps.residents.models import ResidentCompany, ResidentEmployee, AccessEvent


def _norm_name(value: str) -> str:
    return " ".join((value or "").split()).casefold()


def _company_index() -> tuple[dict[int, ResidentCompany], dict[str, ResidentCompany]]:
    by_id: dict[int, ResidentCompany] = {}
    by_name: dict[str, ResidentCompany] = {}
    for company in ResidentCompany.objects.all():
        by_id[company.pk] = company
        key = _norm_name(company.name)
        if key and key not in by_name:
            by_name[key] = company
    return by_id, by_name


def _employee_name_index() -> dict[str, list[ResidentEmployee]]:
    index: dict[str, list[ResidentEmployee]] = defaultdict(list)
    for emp in ResidentEmployee.objects.select_related("company").all():
        key = _norm_name(emp.full_name)
        if key:
            index[key].append(emp)
    return index


def _pick_employee(
    candidates: list[ResidentEmployee],
    *,
    company_id: int | None,
    company_name: str,
    card_number: str,
) -> ResidentEmployee | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    scored: list[tuple[tuple, ResidentEmployee]] = []
    want_co = _norm_name(company_name)
    want_card = (card_number or "").strip()
    for emp in candidates:
        company_hit = 0
        if company_id and emp.company_id == company_id:
            company_hit = 2
        elif want_co and _norm_name(emp.company.name if emp.company_id else "") == want_co:
            company_hit = 1
        card_hit = 1 if want_card and (emp.card_number or "").strip() == want_card else 0
        # Prefer active current staff, then higher pk (newer AxTrax link)
        scored.append(((company_hit, card_hit, int(emp.is_active), emp.pk), emp))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _resolve_company_for_stub(
    *,
    company_id: int | None,
    company_name: str,
    by_id: dict[int, ResidentCompany],
    by_name: dict[str, ResidentCompany],
    fallback: ResidentCompany | None,
) -> ResidentCompany | None:
    if company_id and company_id in by_id:
        return by_id[company_id]
    key = _norm_name(company_name)
    if key and key in by_name:
        return by_name[key]
    return fallback


def rematch_access_events(*, dry_run: bool = False, create_missing: bool = True) -> dict:
    """Move mismatched AccessEvent.employee FKs onto the snapshot person.

    Keeps ``employee_name``, ``card_number``, ``company_id``, ``company_name``
    snapshots as punch-time truth (does not overwrite them from the target).
    """
    by_id, by_name = _company_index()
    name_index = _employee_name_index()

    mismatch_qs = (
        AccessEvent.objects.exclude(employee_id=None)
        .exclude(employee_name="")
        .exclude(employee_name=F("employee__full_name"))
    )

    # Group by snapshot identity so we resolve once per person/card/company bucket.
    groups = (
        mismatch_qs.values("employee_name", "company_id", "company_name", "card_number")
        .annotate(c=Count("id"))
        .order_by("-c")
    )

    stats = {
        "mismatch_events": mismatch_qs.count(),
        "groups": 0,
        "reassigned_events": 0,
        "created_employees": 0,
        "unresolved_groups": 0,
        "unresolved_events": 0,
        "skipped_same_target": 0,
        "dry_run": dry_run,
    }
    samples: list[dict] = []

    fallback_company = (
        ResidentCompany.objects.filter(is_internal=True).order_by("pk").first()
        or ResidentCompany.objects.order_by("pk").first()
    )

    for group in groups:
        stats["groups"] += 1
        snap_name = group["employee_name"]
        key = _norm_name(snap_name)
        company_id = group["company_id"]
        company_name = group["company_name"] or ""
        card_number = group["card_number"] or ""
        count = int(group["c"])

        candidates = list(name_index.get(key) or [])
        target = _pick_employee(
            candidates,
            company_id=company_id,
            company_name=company_name,
            card_number=card_number,
        )

        if target is None and create_missing:
            company = _resolve_company_for_stub(
                company_id=company_id,
                company_name=company_name,
                by_id=by_id,
                by_name=by_name,
                fallback=fallback_company,
            )
            if company is None:
                stats["unresolved_groups"] += 1
                stats["unresolved_events"] += count
                if len(samples) < 25:
                    samples.append(
                        {
                            "employee_name": snap_name,
                            "count": count,
                            "reason": "no_company_for_stub",
                        }
                    )
                continue
            if dry_run:
                stats["created_employees"] += 1
                stats["reassigned_events"] += count
                if len(samples) < 25:
                    samples.append(
                        {
                            "employee_name": snap_name,
                            "count": count,
                            "action": "would_create_and_reassign",
                            "company": company.name,
                        }
                    )
                continue
            with transaction.atomic():
                target = ResidentEmployee.objects.create(
                    company=company,
                    full_name=snap_name[:160],
                    card_number="",
                    is_active=False,
                    deactivated_at=timezone.now(),
                )
                stats["created_employees"] += 1
                name_index[key].append(target)
        elif target is None:
            stats["unresolved_groups"] += 1
            stats["unresolved_events"] += count
            if len(samples) < 25:
                samples.append(
                    {
                        "employee_name": snap_name,
                        "count": count,
                        "reason": "no_employee_match",
                    }
                )
            continue

        qs = mismatch_qs.filter(
            employee_name=snap_name,
            company_id=company_id,
            company_name=company_name,
            card_number=card_number,
        ).exclude(employee_id=target.pk)
        move_count = qs.count()
        already = count - move_count
        if already:
            stats["skipped_same_target"] += already
        if not move_count:
            continue

        if dry_run:
            stats["reassigned_events"] += move_count
            if len(samples) < 25:
                samples.append(
                    {
                        "employee_name": snap_name,
                        "count": move_count,
                        "action": "would_reassign",
                        "target_id": target.pk,
                        "target_name": target.full_name,
                    }
                )
            continue

        updated = qs.update(employee_id=target.pk)
        stats["reassigned_events"] += updated
        if len(samples) < 25:
            samples.append(
                {
                    "employee_name": snap_name,
                    "count": updated,
                    "action": "reassigned",
                    "target_id": target.pk,
                    "target_name": target.full_name,
                }
            )

    stats["samples"] = samples

    # Case / whitespace-only drift: keep FK, normalize snapshot to current full_name.
    case_fixed = _fix_case_only_names(dry_run=dry_run)
    stats["case_normalized_events"] = case_fixed

    empty_stats = _rematch_empty_names_by_card(dry_run=dry_run)
    stats.update(empty_stats)
    return stats


def _fix_case_only_names(*, dry_run: bool) -> int:
    qs = (
        AccessEvent.objects.exclude(employee_id=None)
        .exclude(employee_name="")
        .exclude(employee_name=F("employee__full_name"))
    )
    fixed = 0
    for ev in qs.iterator(chunk_size=500):
        if _norm_name(ev.employee_name) != _norm_name(ev.employee.full_name):
            continue
        if dry_run:
            fixed += 1
            continue
        AccessEvent.objects.filter(pk=ev.pk).update(employee_name=ev.employee.full_name[:160])
        fixed += 1
    return fixed


def _card_owner_from_named_events() -> dict[str, tuple[int, str, int | None, str]]:
    """card → (employee_id, employee_name, company_id, company_name) from named punches."""
    rows = (
        AccessEvent.objects.exclude(card_number="")
        .exclude(employee_name="")
        .exclude(employee_id=None)
        .values("card_number", "employee_id", "employee_name", "company_id", "company_name")
        .annotate(c=Count("id"))
        .order_by("card_number", "-c")
    )
    winners: dict[str, tuple[int, str, int | None, str]] = {}
    for row in rows:
        card = (row["card_number"] or "").strip()
        if not card or card in winners:
            continue
        winners[card] = (
            int(row["employee_id"]),
            row["employee_name"],
            row["company_id"],
            row["company_name"] or "",
        )
    return winners


def _rematch_empty_names_by_card(*, dry_run: bool) -> dict:
    """Empty employee_name punches: fill name, or move when card belongs to someone else.

    Only reassign when the punch card differs from the linked employee's current
    badge — typical leftover after AxTrax emp-id reuse.
    """
    owners = _card_owner_from_named_events()
    emp_cards = {
        pk: (card or "").strip()
        for pk, card in ResidentEmployee.objects.values_list("pk", "card_number")
    }
    empty_qs = AccessEvent.objects.exclude(employee_id=None).filter(employee_name="").exclude(
        card_number=""
    )
    stats = {
        "empty_name_events": empty_qs.count(),
        "empty_name_reassigned": 0,
        "empty_name_filled": 0,
        "empty_name_unresolved": 0,
    }
    groups = empty_qs.values("employee_id", "card_number").annotate(c=Count("id"))
    for group in groups:
        card = (group["card_number"] or "").strip()
        current_id = int(group["employee_id"])
        count = int(group["c"])
        current_card = emp_cards.get(current_id, "")
        owner = owners.get(card)

        # Wrong-badge leftovers → dominant named owner of that card
        if owner and owner[0] != current_id and card and card != current_card:
            owner_id, owner_name, _co_id, _co_name = owner
            if dry_run:
                stats["empty_name_reassigned"] += count
                continue
            updated = empty_qs.filter(
                employee_id=current_id, card_number=group["card_number"]
            ).update(employee_id=owner_id, employee_name=owner_name[:160])
            stats["empty_name_reassigned"] += updated
            continue

        fill_name = (owner[1] if owner and owner[0] == current_id else "") or ""
        if not fill_name:
            emp_name = (
                ResidentEmployee.objects.filter(pk=current_id)
                .values_list("full_name", flat=True)
                .first()
            )
            fill_name = emp_name or ""
        if not fill_name:
            stats["empty_name_unresolved"] += count
            continue
        if dry_run:
            stats["empty_name_filled"] += count
            continue
        updated = empty_qs.filter(
            employee_id=current_id, card_number=group["card_number"]
        ).update(employee_name=fill_name[:160])
        stats["empty_name_filled"] += updated
    return stats
