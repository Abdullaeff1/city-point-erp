"""Central ticket visibility and mutation ACL (department-scoped).

Dual gate: department/role rules AND PermissionCode ticket.view / ticket.edit.
"""

from __future__ import annotations

from django.db.models import QuerySet

from apps.accounts.models import Role, User
from apps.rbac.services import user_has_permission
from apps.tickets.models import DELETABLE_STATUSES, Ticket


def can_view_all_tickets(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.role not in {Role.ADMIN, Role.MANAGEMENT}:
        return False
    return user_has_permission(user, "ticket.view")


def user_ticket_department(user):
    if not user or not getattr(user, "is_authenticated", False):
        return None
    dept = getattr(user, "ticket_department", None)
    if dept is not None:
        return dept
    from apps.tickets.routing import department_code_for_role
    from apps.tickets.models import TicketDepartment

    code = department_code_for_role(getattr(user, "role", None))
    if not code:
        return None
    return TicketDepartment.objects.filter(code=code, is_active=True).first()


def tickets_visible_to(user) -> QuerySet[Ticket]:
    """Staff queryset for ticket lists/details. Residents use company scoping in portal views."""
    from apps.tickets.routing import effective_ticket_department_ids

    base = Ticket.objects.all()
    if not user or not getattr(user, "is_authenticated", False):
        return base.none()
    if can_view_all_tickets(user):
        return base
    dept_ids = effective_ticket_department_ids(user)
    if not dept_ids:
        return base.none()
    return base.filter(department_id__in=dept_ids)


def can_view_ticket(user, ticket) -> bool:
    """Staff department visibility (not for resident company scope)."""
    from apps.tickets.routing import effective_ticket_department_ids

    if not user or not getattr(user, "is_authenticated", False) or ticket is None:
        return False
    if not user_has_permission(user, "ticket.view"):
        return False
    if can_view_all_tickets(user):
        return True
    dept_ids = effective_ticket_department_ids(user)
    if not dept_ids:
        return False
    return ticket.department_id in dept_ids


def can_mutate_ticket(user, ticket) -> bool:
    """Staff may mutate own-dept tickets; residents never mutate staff workflow."""
    if not user or not getattr(user, "is_authenticated", False) or ticket is None:
        return False
    role = getattr(user, "role", None)
    if role == Role.RESIDENT_USER:
        return False
    # Rəhbərlik yalnız nəticə görür — dəyişiklik service desk / FM-dədir.
    if role == Role.MANAGEMENT:
        return False
    if not user_has_permission(user, "ticket.edit"):
        return False
    return can_view_ticket(user, ticket)


def can_access_ticket_attachment(user, ticket, *, company_ids=None, attachment=None) -> bool:
    """Staff: department view. Resident: company scope AND attachment explicitly portal-visible.

    A shared ticket / company link never publishes an internal staff file.
    """
    if not user or not getattr(user, "is_authenticated", False) or ticket is None:
        return False
    if getattr(user, "role", None) == Role.RESIDENT_USER:
        if attachment is not None and not getattr(attachment, "visible_to_resident", False):
            return False
        from apps.accounts.object_scope import company_accessible

        return company_accessible(user, ticket.company_id, company_ids=company_ids)
    return can_view_ticket(user, ticket)


def can_handoff_ticket(user, ticket) -> bool:
    """The department that holds the ticket, and leadership, may send it elsewhere."""
    return can_mutate_ticket(user, ticket)


def can_delete_ticket(user, ticket, *, company_ids=None) -> bool:
    """Delete only before İcradadır: staff of the ticket dept, or scoped portal user."""
    if not user or not getattr(user, "is_authenticated", False) or ticket is None:
        return False
    if ticket.status not in DELETABLE_STATUSES:
        return False
    if getattr(user, "role", None) == Role.RESIDENT_USER:
        from apps.accounts.object_scope import company_accessible

        return company_accessible(user, ticket.company_id, company_ids=company_ids)
    return can_mutate_ticket(user, ticket)


def department_assignees(ticket) -> QuerySet[User]:
    """Active staff users belonging to the ticket's department."""
    if not ticket or not ticket.department_id:
        return User.objects.none()
    return User.objects.filter(
        is_active=True,
        ticket_department_id=ticket.department_id,
    ).exclude(role=Role.RESIDENT_USER)
