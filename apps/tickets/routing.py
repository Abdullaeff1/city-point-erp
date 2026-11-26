"""Ticket routing defaults: subcategory rule → category fallback → role dept."""

from __future__ import annotations

from apps.accounts.models import Role

# Portal category slug → default queue code (queue owns the department).
CATEGORY_DEFAULT_QUEUE = {
    "technical": "technical",
    "cleaning": "cleaning",
    "security": "security",
    "parking": "parking",
    "commercial-space": "leasing",
    "lease": "contract",
    "billing": "ar",
    "administration": "docs",
    "other": "general",
    # Legacy category slugs (pre-taxonomy).
    "electric": "electric",
    "hvac": "hvac",
    "access": "security",
}

# Staff role → ticket department when User.ticket_department is empty (server drift).
ROLE_DEFAULT_DEPARTMENT = {
    Role.SECURITY: "security",
    # Unified Təchizat: taxonomy still routes most work to servicedesk;
    # unbound staff also see webservis via supply_ticket_department_ids().
    Role.SERVICE_DESK: "servicedesk",
}

# Legacy Helpdesk + Facility department codes owned by the Supply portal.
SUPPLY_TICKET_DEPARTMENT_CODES = frozenset({"servicedesk", "webservis"})


def queue_code_for_category(category) -> str | None:
    if not category:
        return None
    return CATEGORY_DEFAULT_QUEUE.get(getattr(category, "slug", None) or "")


def fallback_department_and_queue(category):
    """When RoutingRule is missing, route by category slug → queue → department."""
    from apps.tickets.models import TicketQueue

    qcode = queue_code_for_category(category) or "general"
    queue = (
        TicketQueue.objects.filter(code=qcode, is_active=True)
        .select_related("department")
        .first()
    )
    if queue and queue.department_id:
        return queue.department, queue
    return None, None


def department_code_for_role(role: str | None) -> str | None:
    if not role:
        return None
    return ROLE_DEFAULT_DEPARTMENT.get(role)


def effective_ticket_department_id(user) -> int | None:
    """Primary dept for list/detail ACL. Prefer explicit FK; else role default."""
    ids = effective_ticket_department_ids(user)
    return ids[0] if ids else None


def effective_ticket_department_ids(user) -> list[int]:
    """Department ids visible for ticket ACL.

    Explicit ``ticket_department`` keeps a team binding.
    Unbound SERVICE_DESK sees both legacy Supply departments (servicedesk + webservis).
    """
    if not user or not getattr(user, "is_authenticated", False):
        return []
    from apps.tickets.models import TicketDepartment

    dept_id = getattr(user, "ticket_department_id", None)
    if dept_id:
        return [int(dept_id)]
    role = getattr(user, "role", None)
    if role == Role.SERVICE_DESK:
        return list(
            TicketDepartment.objects.filter(
                code__in=SUPPLY_TICKET_DEPARTMENT_CODES,
                is_active=True,
            )
            .order_by("code")
            .values_list("id", flat=True)
        )
    code = department_code_for_role(role)
    if not code:
        return []
    dept = TicketDepartment.objects.filter(code=code, is_active=True).only("id").first()
    return [dept.pk] if dept else []
