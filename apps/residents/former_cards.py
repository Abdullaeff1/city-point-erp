"""Köhnə (deaktiv) əməkdaşların kart nömrəsini AccessEvent tarixçəsindən bərpa."""

from __future__ import annotations

from django.db.models import Count, Max, Q

from apps.residents.models import AccessEvent, ResidentEmployee


def infer_card_from_events(employee_id: int) -> str:
    """Ən çox istifadə olunan kart; bərabərlikdə ən son istifadə olunan."""
    rows = list(
        AccessEvent.objects.filter(employee_id=employee_id)
        .exclude(Q(card_number="") | Q(card_number__isnull=True))
        .values("card_number")
        .annotate(uses=Count("id"), last_at=Max("occurred_at"))
        .order_by("-uses", "-last_at")
    )
    if not rows:
        return ""
    return (rows[0]["card_number"] or "").strip()


def backfill_former_employee_cards(*, apply: bool = False) -> dict:
    """Boş kartlı deaktiv işçilərə tarixçədən kart yaz; boş AccessEvent kartlarını doldur.

    Returns stats dict. ``apply=False`` yalnız sayır.
    """
    stats = {
        "former_empty": 0,
        "inferred": 0,
        "employees_updated": 0,
        "events_updated": 0,
        "no_history": 0,
        "skipped_already_set": 0,
    }
    former = (
        ResidentEmployee.objects.filter(is_active=False)
        .only("pk", "card_number", "full_name")
        .order_by("pk")
    )
    updates: list[tuple[ResidentEmployee, str]] = []
    for emp in former:
        current = (emp.card_number or "").strip()
        if current:
            stats["skipped_already_set"] += 1
            continue
        stats["former_empty"] += 1
        inferred = infer_card_from_events(emp.pk)
        if not inferred:
            stats["no_history"] += 1
            continue
        stats["inferred"] += 1
        updates.append((emp, inferred))

    if apply:
        for emp, card in updates:
            ResidentEmployee.objects.filter(pk=emp.pk).update(card_number=card)
            stats["employees_updated"] += 1
            # Boş snapshota malik keçidləri də eyni kartla doldur (tarixçəni örtmədən).
            n = AccessEvent.objects.filter(employee_id=emp.pk).filter(
                Q(card_number="") | Q(card_number__isnull=True)
            ).update(card_number=card)
            stats["events_updated"] += n
    else:
        stats["employees_would_update"] = len(updates)
        # Estimate empty events for dry-run
        ids = [e.pk for e, _ in updates]
        if ids:
            stats["events_would_update"] = AccessEvent.objects.filter(
                employee_id__in=ids
            ).filter(Q(card_number="") | Q(card_number__isnull=True)).count()
        else:
            stats["events_would_update"] = 0

    return stats
