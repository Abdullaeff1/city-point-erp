"""A.2 — ticket_type → allowed category slugs + form type choices."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.tickets.models import TicketCategory, TicketType

# None = all active categories
TYPE_CATEGORY_SLUGS: dict[str, tuple[str, ...] | None] = {
    TicketType.INCIDENT: ("technical", "cleaning", "security", "parking", "other"),
    TicketType.SERVICE_REQUEST: ("technical", "security", "cleaning", "other"),
    TicketType.COMMERCIAL: (
        "commercial-space",
        "lease",
        "billing",
        "administration",
        "other",
    ),
    TicketType.COMPLAINT: None,
}


def ticket_type_choices_for_forms() -> list[tuple[str, str]]:
    """UI choices without Təklif (suggestion). Legacy DB values may still exist."""
    return [c for c in TicketType.choices if c[0] != TicketType.SUGGESTION]


def allowed_category_slugs(ticket_type: str | None) -> tuple[str, ...] | None:
    if not ticket_type:
        return TYPE_CATEGORY_SLUGS[TicketType.INCIDENT]
    if ticket_type == TicketType.SUGGESTION:
        return ()
    return TYPE_CATEGORY_SLUGS.get(ticket_type, TYPE_CATEGORY_SLUGS[TicketType.INCIDENT])


def categories_for_ticket_type(ticket_type: str | None) -> QuerySet[TicketCategory]:
    qs = TicketCategory.objects.filter(is_active=True).order_by("sort_order", "name")
    slugs = allowed_category_slugs(ticket_type)
    if slugs is None:
        return qs
    if not slugs:
        return qs.none()
    return qs.filter(slug__in=slugs)


def category_allowed_for_type(ticket_type: str | None, category: TicketCategory | None) -> bool:
    if category is None or not category.is_active:
        return False
    slugs = allowed_category_slugs(ticket_type)
    if slugs is None:
        return True
    return category.slug in slugs


def type_category_map_payload() -> dict[str, list[dict]]:
    """JSON for portal/ERP: ticket_type → [{id, name, slug, sort}, ...]."""
    all_cats = list(
        TicketCategory.objects.filter(is_active=True)
        .order_by("sort_order", "name")
        .only("id", "name", "slug", "sort_order")
    )
    by_slug = {c.slug: c for c in all_cats}
    payload: dict[str, list[dict]] = {}
    for ticket_type, _label in ticket_type_choices_for_forms():
        slugs = allowed_category_slugs(ticket_type)
        if slugs is None:
            cats = all_cats
        else:
            cats = [by_slug[s] for s in slugs if s in by_slug]
        payload[ticket_type] = [
            {"id": c.pk, "name": c.name, "slug": c.slug, "sort": c.sort_order} for c in cats
        ]
    return payload
