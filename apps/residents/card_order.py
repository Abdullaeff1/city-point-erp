"""A.3 — card order status machine (Security-only)."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.residents.models import CardOrderStatus, ResidentEmployee
from apps.tickets.models import CLOSED_STATUSES, Ticket, TicketStatus

# approved is retained on the model for legacy rows but not offered in UI.
CARD_ORDER_TRANSITIONS: dict[str, frozenset[str]] = {
    CardOrderStatus.SUBMITTED: frozenset(
        {
            CardOrderStatus.UNDER_REVIEW,
            CardOrderStatus.REJECTED,
            CardOrderStatus.CANCELLED,
        }
    ),
    CardOrderStatus.UNDER_REVIEW: frozenset(
        {
            CardOrderStatus.PREPARED,
            CardOrderStatus.REJECTED,
            CardOrderStatus.CANCELLED,
        }
    ),
    CardOrderStatus.APPROVED: frozenset(
        {
            CardOrderStatus.PREPARED,
            CardOrderStatus.REJECTED,
            CardOrderStatus.CANCELLED,
        }
    ),
    CardOrderStatus.PREPARED: frozenset(
        {
            CardOrderStatus.ISSUED,
            CardOrderStatus.REJECTED,
            CardOrderStatus.CANCELLED,
        }
    ),
}

PENDING_CARD_ORDER_STATUSES = frozenset(
    {
        CardOrderStatus.SUBMITTED,
        CardOrderStatus.UNDER_REVIEW,
        CardOrderStatus.APPROVED,
        CardOrderStatus.PREPARED,
    }
)

TERMINAL_CARD_ORDER_STATUSES = frozenset(
    {
        CardOrderStatus.ISSUED,
        CardOrderStatus.REJECTED,
        CardOrderStatus.CANCELLED,
    }
)


def can_change_card_order_status(user) -> bool:
    """A.3: only Security role advances card-order status (not Admin/Management)."""
    return bool(user and getattr(user, "is_authenticated", False) and user.role == Role.SECURITY)


def allowed_card_order_targets(current: str) -> list[str]:
    return sorted(CARD_ORDER_TRANSITIONS.get(current, frozenset()))


def _close_related_card_order_ticket(employee: ResidentEmployee, actor=None, note: str = "") -> None:
    """Force-close open card-order tickets (may skip linear STATUS_FLOW)."""
    from apps.tickets.services import record_status_event

    tickets = (
        Ticket.objects.filter(
            related_employee=employee,
            subcategory__slug="card-order",
        )
        .exclude(status__in=CLOSED_STATUSES)
        .order_by("-created_at")
    )
    close_note = (note or f"Kart sifarişi: {employee.get_card_order_status_display()}")[:500]
    for ticket in tickets:
        previous = ticket.status
        update_fields = ["status", "updated_at"]
        if employee.card_order_status in {
            CardOrderStatus.REJECTED,
            CardOrderStatus.CANCELLED,
        }:
            ticket.status = TicketStatus.CANCELLED
        else:
            ticket.status = TicketStatus.CLOSED
            ticket.resolution_note = close_note
            update_fields.append("resolution_note")
        ticket.save(update_fields=update_fields)
        record_status_event(
            ticket,
            ticket.status,
            actor=actor,
            from_status=previous,
            note=close_note,
        )


@transaction.atomic
def set_card_order_status(*, employee: ResidentEmployee, new_status: str, actor) -> ResidentEmployee:
    if not can_change_card_order_status(actor):
        raise PermissionDenied(_("Kart sifarişi statusunu yalnız təhlükəsizlik dəyişə bilər."))
    current = employee.card_order_status or CardOrderStatus.NONE
    if new_status not in CARD_ORDER_TRANSITIONS.get(current, frozenset()):
        raise DomainError(
            _("Bu keçid icazəli deyil: %(from)s → %(to)s")
            % {
                "from": employee.get_card_order_status_display(),
                "to": dict(CardOrderStatus.choices).get(new_status, new_status),
            }
        )
    employee.card_order_status = new_status
    employee.save(update_fields=["card_order_status"])
    if new_status in TERMINAL_CARD_ORDER_STATUSES:
        _close_related_card_order_ticket(
            employee,
            actor=actor,
            note=f"Kart sifarişi statusu: {employee.get_card_order_status_display()}",
        )
    return employee


@transaction.atomic
def mark_card_order_issued_from_axtrax(employee: ResidentEmployee) -> bool:
    """When AxTrax writes a badge, pending orders become issued (no manual card_number)."""
    status = employee.card_order_status or CardOrderStatus.NONE
    if status not in PENDING_CARD_ORDER_STATUSES:
        return False
    if not (employee.card_number or "").strip():
        return False
    employee.card_order_status = CardOrderStatus.ISSUED
    employee.save(update_fields=["card_order_status"])
    _close_related_card_order_ticket(
        employee,
        actor=None,
        note="AxTrax sync: kart nömrəsi alındı",
    )
    return True
