"""Work Order ACL — Facility inbox + ticket-scoped visibility (Phase 4.2.1 / 4.4.2.1).

Preserves ticket confidentiality: viewing a WO does not grant ticket mutate rights.
Management remains read-only on WO mutations.
WO access uses work_order.* permissions — not ticket.view as a hard gate.
"""

from __future__ import annotations

from django.db.models import Q

from apps.accounts.models import Role
from apps.rbac.services import user_has_permission
from apps.tickets.access import can_mutate_ticket, can_view_ticket, tickets_visible_to


def _facility_ops_role(user) -> bool:
    role = getattr(user, "role", None)
    return role in {Role.PROPERTY_FM, Role.ADMIN, Role.MANAGEMENT}


def can_create_standalone_work_order(user) -> bool:
    """Facility-originated WO (no ticket). Helpdesk creates via ticket path only."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    role = getattr(user, "role", None)
    if role == Role.MANAGEMENT:
        return False
    if role not in {Role.PROPERTY_FM, Role.ADMIN}:
        return False
    return user_has_permission(user, "work_order.create") or user_has_permission(
        user, "work_order.edit"
    )


def work_orders_queryset_for(user):
    """WOs visible via ticket dept, Facility inbox, assignee, or orphan coverage."""
    from apps.maintenance.models import WorkOrder

    if not user or not getattr(user, "is_authenticated", False):
        return WorkOrder.objects.none()
    if not user_has_permission(user, "work_order.view"):
        return WorkOrder.objects.none()

    visible_tickets = tickets_visible_to(user)
    q = Q(ticket__in=visible_tickets) | Q(assigned_to_id=user.pk)

    if _facility_ops_role(user):
        # Facility / Admin / Management inbox: ticket-linked + orphan / standalone WOs
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
        # Orphan / PM / Facility standalone WO — Facility ops + Admin/Management view
        return _facility_ops_role(user)
    if can_view_ticket(user, wo.ticket):
        return True
    # Facility inbox: FM/Admin/Management may view ticket-linked WOs without ticket dept match
    return _facility_ops_role(user)


def can_mutate_work_order(user, wo) -> bool:
    """Mutate WO status/costs. Management RO. FM may operate Facility inbox WOs."""
    if not can_view_work_order(user, wo):
        return False
    role = getattr(user, "role", None)
    if role == Role.MANAGEMENT:
        return False
    if not user_has_permission(user, "work_order.edit"):
        return False
    if wo.ticket_id is None:
        return role in {Role.PROPERTY_FM, Role.ADMIN}
    if can_mutate_ticket(user, wo.ticket):
        return True
    if role == Role.ADMIN:
        return True
    if role == Role.PROPERTY_FM:
        return True
    return False
