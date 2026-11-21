"""IT operator access helpers — ERP audit vs permission catalog."""

from __future__ import annotations

from apps.accounts.impersonation import can_start_impersonation, get_impersonator
from apps.accounts.models import Role
from apps.rbac.services import user_has_permission


def can_access_erp_audit(user, request=None) -> bool:
    """ERP audit timeline is Admin-only (incl. Admin impersonation preview).

    ``audit.view`` alone is not enough — Management may hold the catalog
    permission for IT dashboard entry without opening the sensitive timeline.
    While an Admin previews another role, the impersonator (not the effective
    role) remains the authority for the sensitive timeline so IT can verify
    the journal without leaving preview. Ordinary Service Desk users never
    gain this privilege; only ``SESSION_IMPERSONATOR_ID`` + Admin gate does.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if request is not None:
        impersonator = get_impersonator(request)
        if impersonator is not None and can_start_impersonation(impersonator):
            return True
    if not user_has_permission(user, "audit.view"):
        return False
    return getattr(user, "role", None) == Role.ADMIN


def staff_users_queryset():
    """Internal ERP login accounts — exclude resident portal users."""
    from apps.accounts.models import User

    return (
        User.objects.exclude(role=Role.RESIDENT_USER)
        .select_related("ticket_department")
        .order_by("role", "username")
    )
