"""Work Order ACL — Təchizat inbox + ticket-scoped visibility (Phase 4.2.1 / 4.4.2.1).

Preserves ticket confidentiality: viewing a WO does not grant ticket mutate rights.
Management remains read-only on WO mutations.
WO access uses work_order.* permissions — not ticket.view as a hard gate.
"""

from __future__ import annotations

from django.db.models import Q

from apps.accounts.models import Role
from apps.rbac.services import user_has_permission
from apps.tickets.access import can_mutate_ticket, can_view_ticket, tickets_visible_to


def _supply_ops_role(user) -> bool:
    """Təchizat inbox + designated Supply head (explicit supply.head)."""
    from apps.accounts.supply import is_supply_head

    role = getattr(user, "role", None)
    if role in {Role.SERVICE_DESK, Role.ADMIN, Role.MANAGEMENT}:
        return True
    return is_supply_head(user)


def can_create_standalone_work_order(user) -> bool:
    """Standalone WO: Təchizat staff, Admin, or designated Supply head."""
    from apps.accounts.supply import is_supply_head

    if not user or not getattr(user, "is_authenticated", False):
        return False
    role = getattr(user, "role", None)
    if role == Role.MANAGEMENT:
        return False
    if role not in {Role.SERVICE_DESK, Role.ADMIN} and not is_supply_head(user):
        return False
    return user_has_permission(user, "work_order.create") or user_has_permission(
        user, "work_order.edit"
    )


def work_orders_queryset_for(user):
    """WOs visible via ticket dept, Təchizat inbox, assignee, or orphan coverage."""
    from apps.maintenance.models import WorkOrder

    if not user or not getattr(user, "is_authenticated", False):
        return WorkOrder.objects.none()
    if not user_has_permission(user, "work_order.view"):
        return WorkOrder.objects.none()

    visible_tickets = tickets_visible_to(user)
    q = Q(ticket__in=visible_tickets) | Q(assigned_to_id=user.pk)

    if _supply_ops_role(user):
        # Təchizat / Admin / Management inbox: ticket-linked + orphan / standalone WOs
        q |= Q(ticket__isnull=False) | Q(ticket__isnull=True)

    return (
        WorkOrder.objects.filter(q)
        .distinct()
        .select_related(
            "ticket",
            "ticket__company",
            "ticket__department",
            "space",
            "contractor",
            "assigned_to",
        )
        .order_by("-created_at")
    )


def can_view_work_order(user, wo) -> bool:
    if not user or not getattr(user, "is_authenticated", False) or wo is None:
        return False
    if not user_has_permission(user, "work_order.view"):
        return False
    if wo.assigned_to_id and wo.assigned_to_id == user.pk:
        return True
    if wo.ticket_id is None:
        # Orphan / PM / standalone WO — Təchizat ops + Admin/Management view
        return _supply_ops_role(user)
    if can_view_ticket(user, wo.ticket):
        return True
    # Təchizat inbox: may view ticket-linked WOs without ticket dept match
    return _supply_ops_role(user)


def can_mutate_work_order(user, wo) -> bool:
    """Mutate WO status/costs. Management RO. Təchizat may operate inbox WOs."""
    if not can_view_work_order(user, wo):
        return False
    role = getattr(user, "role", None)
    if role == Role.MANAGEMENT:
        return False
    if not user_has_permission(user, "work_order.edit"):
        return False
    from apps.accounts.supply import is_supply_head

    if wo.ticket_id is None:
        return role in {Role.SERVICE_DESK, Role.ADMIN} or is_supply_head(user)
    if can_mutate_ticket(user, wo.ticket):
        return True
    if role == Role.ADMIN:
        return True
    if role == Role.SERVICE_DESK or is_supply_head(user):
        return True
    return False
