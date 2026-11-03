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
    Role.SERVICE_DESK: "servicedesk",
    Role.PROPERTY_FM: "webservis",
}


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
    """Dept used for list/detail ACL. Prefer explicit FK; else role default."""
    if not user or not getattr(user, "is_authenticated", False):
        return None
    dept_id = getattr(user, "ticket_department_id", None)
    if dept_id:
        return dept_id
    code = department_code_for_role(getattr(user, "role", None))
    if not code:
        return None
    from apps.tickets.models import TicketDepartment

    dept = TicketDepartment.objects.filter(code=code, is_active=True).only("id").first()
    return dept.pk if dept else None
