"""Work Order ACL — scoped Təchizat inbox (ordinary staff vs supply.head).

Preserves ticket confidentiality: viewing a WO does not grant ticket mutate rights.
Management remains read-only on WO mutations.
WO access uses work_order.* permissions — not ticket.view as a hard gate.

Ownership evidence (WorkOrder has no department field):
- assigned_to → personal assignment
- ticket.department match via tickets_visible_to / can_mutate_ticket → team route
- supply.head / Admin → facility inbox (handoffs + orphan / standalone PM)
- ticket_id is None without inbox role → deny (no global orphan edit)
"""

from __future__ import annotations

from django.db.models import Q

from apps.accounts.models import Role
from apps.rbac.services import user_has_permission
from apps.tickets.access import can_mutate_ticket, can_view_ticket, tickets_visible_to


def _facility_inbox_viewer(user) -> bool:
    """Admin, Management (RO), or designated Head of Supply — not ordinary SERVICE_DESK."""
    from apps.accounts.supply import is_supply_head

    role = getattr(user, "role", None)
    if role in {Role.ADMIN, Role.MANAGEMENT}:
        return True
    return is_supply_head(user)


def _facility_inbox_operator(user) -> bool:
    """May mutate facility-inbox / orphan WOs: Admin or supply.head."""
    from apps.accounts.supply import is_supply_head

    role = getattr(user, "role", None)
    if role == Role.ADMIN:
        return True
    if role == Role.MANAGEMENT:
        return False
    return is_supply_head(user)


def can_create_standalone_work_order(user) -> bool:
    """Standalone WO: Admin or designated Supply head only."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "role", None) == Role.MANAGEMENT:
        return False
    if not _facility_inbox_operator(user):
        return False
    return user_has_permission(user, "work_order.create") or user_has_permission(
        user, "work_order.edit"
    )


def work_orders_queryset_for(user):
    """WOs visible via ticket dept, assignee, or facility inbox (head/Admin/Mgmt)."""
    from apps.maintenance.models import WorkOrder

    if not user or not getattr(user, "is_authenticated", False):
        return WorkOrder.objects.none()
    if not user_has_permission(user, "work_order.view"):
        return WorkOrder.objects.none()

    visible_tickets = tickets_visible_to(user)
    q = Q(ticket__in=visible_tickets) | Q(assigned_to_id=user.pk)

    if _facility_inbox_viewer(user):
        # Head / Admin / Management: ticket-linked handoffs + orphan / standalone
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
        # Orphan / PM / standalone — facility inbox viewers only
        return _facility_inbox_viewer(user)
    if can_view_ticket(user, wo.ticket):
        return True
    # Cross-dept handoff inbox (head/Admin/Mgmt) without ticket-dept match
    return _facility_inbox_viewer(user)


def can_mutate_work_order(user, wo) -> bool:
    """Mutate WO status/costs. Management RO. Ordinary staff: own dept or assignee."""
    if not can_view_work_order(user, wo):
        return False
    role = getattr(user, "role", None)
    if role == Role.MANAGEMENT:
        return False
    if not user_has_permission(user, "work_order.edit"):
        return False
    if wo.ticket_id is None:
        return _facility_inbox_operator(user)
    if can_mutate_ticket(user, wo.ticket):
        return True
    if _facility_inbox_operator(user):
        return True
    # Explicit assignee may progress their repair without ticket-dept match
    if wo.assigned_to_id and wo.assigned_to_id == user.pk:
        return True
    return False
