"""Permission-aware navigation flags and department landing resolution (Phase 3).

Templates consume ``nav_*`` booleans only — never call RBAC helpers in Jinja.
"""

from __future__ import annotations

from django.utils.translation import gettext as _

from apps.accounts.models import Role
from apps.comms.announcements import can_publish_announcement
from apps.rbac.services import user_has_permission


def _has(user, *codes: str) -> bool:
    return any(user_has_permission(user, c) for c in codes if c)


# Nav flag → one or more PermissionCode (any-of).
NAV_PERMISSION_MAP: dict[str, tuple[str, ...]] = {
    "nav_reception": ("reception.view", "reception.manage"),
    "nav_tickets": ("ticket.view",),
    "nav_work_orders": ("work_order.view",),
    "nav_property": ("space.view",),
    "nav_building_assets": ("property.asset.view", "space.view"),
    "nav_residents": ("resident.view",),
    "nav_docs": ("document.view",),
    "nav_reports": ("report.view",),
    "nav_approvals": ("approval.view",),
    "nav_internal_access": ("hr.view",),
    "nav_crm": ("crm.view",),
    "nav_supply": ("warehouse.view", "procurement.view"),
    "nav_finance": ("finance.view",),
    # ERP audit timeline is Admin-enforced; do not advertise via bare audit.view
    # (Management holds audit.view for IT dashboard entry but cannot open erp:audit).
    "nav_audit": ("user.admin",),
    "nav_staff_users": ("user.view", "user.admin"),
    "nav_parties": ("party.view",),
}

# Ordered workspaces for landing fallback + sidebar switcher.
WORKSPACE_CATALOG: tuple[dict, ...] = (
    {
        "key": "management",
        "label": _("Rəhbərlik"),
        "url_name": "erp:dashboard",
        "perms": ("approval.view", "report.view"),
        "roles_prefer": (Role.MANAGEMENT,),
    },
    {
        "key": "sales",
        "label": _("Satış / CRM"),
        "url_name": "erp:dashboard",
        "perms": ("crm.view",),
        "roles_prefer": (Role.SALES,),
    },
    {
        "key": "reception",
        "label": _("Qəbul"),
        "url_name": "erp:reception",
        "perms": ("reception.view", "reception.manage"),
        "roles_prefer": (Role.RECEPTION,),
    },
    {
        "key": "security",
        "label": _("Təhlükəsizlik"),
        "url_name": "security:home",
        "perms": ("security.view",),
        "roles_prefer": (Role.SECURITY,),
    },
    {
        "key": "facility",
        "label": _("Obyekt idarəetməsi"),
        "url_name": "erp:facility_dashboard",
        "perms": ("space.view",),
        "roles_prefer": (Role.PROPERTY_FM,),
    },
    {
        "key": "helpdesk",
        "label": _("Helpdesk"),
        "url_name": "erp:helpdesk_dashboard",
        "perms": ("ticket.view",),
        "roles_prefer": (Role.SERVICE_DESK,),
    },
    {
        "key": "finance",
        "label": _("Maliyyə"),
        "url_name": "finance:home",
        "perms": ("finance.view",),
        "roles_prefer": (Role.ACCOUNTANT,),
    },
    {
        "key": "hr",
        "label": _("HR"),
        "url_name": "erp:hr_dashboard",
        "perms": ("hr.view",),
        "roles_prefer": (),
    },
    {
        "key": "procurement",
        "label": _("Satınalma"),
        "url_name": "erp:procurement_dashboard",
        "perms": ("procurement.view",),
        "roles_prefer": (),
    },
    {
        "key": "it",
        "label": _("IT / Admin"),
        "url_name": "erp:it_dashboard",
        "perms": ("user.admin", "audit.view"),
        "roles_prefer": (Role.ADMIN,),
    },
)

# Role → preferred landing (permission still required, except ADMIN / resident).
ROLE_PREFERRED_LANDING: dict[str, tuple[str, tuple[str, ...]]] = {
    Role.MANAGEMENT: ("erp:dashboard", ("approval.view", "report.view")),
    Role.RECEPTION: ("erp:reception", ("reception.view", "reception.manage")),
    Role.SECURITY: ("security:home", ("security.view",)),
    Role.PROPERTY_FM: ("erp:facility_dashboard", ("space.view",)),
    Role.SALES: ("erp:dashboard", ("crm.view",)),
    Role.ACCOUNTANT: ("finance:home", ("finance.view",)),
    Role.SERVICE_DESK: ("erp:helpdesk_dashboard", ("ticket.view",)),
    Role.ADMIN: ("erp:it_dashboard", ()),  # admin bypass
}


def build_nav_flags(user) -> dict:
    """Return ``nav_*`` booleans derived from PermissionCode (not Role alone)."""
    empty = {k: False for k in NAV_PERMISSION_MAP}
    empty.update(
        {
            "nav_announcements": False,
            "nav_leases": False,  # intentionally hidden — data on resident card
            "nav_workspaces": [],
            "nav_show_workspace_switcher": False,
        }
    )
    if not user or not getattr(user, "is_authenticated", False):
        return empty

    flags = {key: _has(user, *codes) for key, codes in NAV_PERMISSION_MAP.items()}
    # Announcements: product helper (includes MANAGEMENT publish).
    flags["nav_announcements"] = bool(can_publish_announcement(user))
    flags["nav_leases"] = False

    # CRM Admin-out (A.10): Admin has all perms but must not see CRM nav.
    if getattr(user, "role", None) == Role.ADMIN:
        flags["nav_crm"] = False

    # Reception desk is role-gated (Reception + Admin); hide dead links for RO viewers.
    if flags.get("nav_reception") and getattr(user, "role", None) not in {
        Role.RECEPTION,
        Role.ADMIN,
    }:
        flags["nav_reception"] = False

    workspaces = list_workspaces(user)
    flags["nav_workspaces"] = workspaces
    flags["nav_show_workspace_switcher"] = len(workspaces) > 1
    return flags


def list_workspaces(user) -> list[dict]:
    """Workspaces the user may open (permission-filtered). Admin sees all."""
    if not user or not getattr(user, "is_authenticated", False):
        return []
    role = getattr(user, "role", None)
    if role == Role.RESIDENT_USER:
        return [
            {
                "key": "portal",
                "label": str(_("Rezident portal")),
                "url_name": "portal:home",
            }
        ]
    out: list[dict] = []
    seen: set[str] = set()
    is_admin = role == Role.ADMIN
    for ws in WORKSPACE_CATALOG:
        key = ws["key"]
        if key in seen:
            continue
        perms = ws["perms"]
        if not (is_admin or (not perms) or _has(user, *perms)):
            continue
        # Portal shells: only list if the user may enter that portal (preserve isolation).
        if key == "security" and not getattr(user, "can_access_security_portal", lambda: False)():
            continue
        if key == "finance" and not getattr(user, "can_access_finance_portal", lambda: False)():
            continue
        # Reception desk is role-gated; don't offer it as a workspace jump for RO roles.
        if key == "reception" and role not in {Role.RECEPTION, Role.ADMIN}:
            continue
        # Sales and management share erp:dashboard — keep both labels if both perms.
        if key == "sales" and role == Role.MANAGEMENT and not user_has_permission(user, "crm.view"):
            continue
        if key == "management" and role == Role.SALES:
            if not _has(user, "approval.view", "report.view"):
                continue
        # Management stays in ERP for security metrics (people_inside) — no /security/ switcher.
        if key == "security" and role == Role.MANAGEMENT:
            continue
        out.append(
            {
                "key": key,
                "label": str(ws["label"]),
                "url_name": ws["url_name"],
            }
        )
        seen.add(key)
    return out


def resolve_landing_url_name(user) -> str:
    """Permission-validated home URL name after login / soft-deny."""
    if not user or not getattr(user, "is_authenticated", False):
        return "login"
    role = getattr(user, "role", None)
    if role == Role.RESIDENT_USER:
        return "portal:home"
    if role == Role.ADMIN:
        return "erp:it_dashboard"

    preferred = ROLE_PREFERRED_LANDING.get(role)
    if preferred:
        url_name, perms = preferred
        if not perms or _has(user, *perms):
            return url_name

    workspaces = list_workspaces(user)
    if workspaces:
        return workspaces[0]["url_name"]
    return "erp:dashboard"
