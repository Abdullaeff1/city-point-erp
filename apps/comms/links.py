"""Where an in-app notification should open, for the portal the user is in."""

import re

from django.urls import reverse

from apps.comms.models import Notification
from apps.tickets.access import can_view_ticket
from apps.tickets.models import Ticket

TICKET_CODE_RE = re.compile(r"\bTK-\d+\b")


def user_notifications(user, *, namespace: str, limit: int = 100):
    notes = list(
        Notification.objects.filter(user=user)
        .select_related("ticket")
        .order_by("-created_at")[:limit]
    )
    missing_codes = []
    for note in notes:
        if note.ticket_id:
            continue
        match = TICKET_CODE_RE.search(note.message or "")
        if match:
            missing_codes.append(match.group(0))
    by_code = {}
    if missing_codes:
        by_code = {
            ticket.code: ticket
            for ticket in Ticket.objects.filter(code__in=set(missing_codes))
        }
    for note in notes:
        ticket = note.ticket if note.ticket_id else None
        if ticket is None:
            match = TICKET_CODE_RE.search(note.message or "")
            ticket = by_code.get(match.group(0)) if match else None
        note.target_url = notification_target_url(note, ticket, user, namespace)
    return notes


def notification_target_url(note, ticket, user, namespace: str) -> str:
    if ticket is not None:
        if namespace == "portal":
            company_id = getattr(user, "resident_company_id", None)
            if company_id and ticket.company_id == company_id:
                return reverse("portal:request_detail", kwargs={"code": ticket.code})
            return ""
        if namespace == "security":
            if can_view_ticket(user, ticket):
                return reverse("security:ticket_detail", kwargs={"code": ticket.code})
            return ""
        if can_view_ticket(user, ticket):
            return reverse("erp:ticket_detail", kwargs={"code": ticket.code})
        return ""

    if namespace != "security":
        return ""
    message = note.message or ""
    if message.startswith("Kart çoxvurma"):
        return reverse("security:alerts_rapid")
    if message.startswith("Şaxta"):
        return reverse("security:alerts_shaft")
    return ""
