from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _

from apps.accounts.models import Role
from apps.rbac.models import PermissionCode, RolePermission

# Foundation catalog — extend per scope; seed is idempotent.
DEFAULT_PERMISSIONS = [
    ("party.view", "Party baxış", "parties"),
    ("party.edit", "Party redaktə", "parties"),
    ("space.view", "Sahə baxış", "property"),
    ("space.edit", "Sahə redaktə", "property"),
    ("property.asset.view", "Avadanlıq / inventar baxış", "property"),
    ("property.asset.edit", "Avadanlıq / inventar redaktə", "property"),
    ("ticket.view", "Ticket baxış", "tickets"),
    ("ticket.create", "Ticket yaratma", "tickets"),
    ("ticket.edit", "Ticket redaktə", "tickets"),
    ("ticket.export", "Ticket export", "tickets"),
    ("work_order.view", "İş sifarişi baxış", "maintenance"),
    ("work_order.create", "İş sifarişi yaratma", "maintenance"),
    ("work_order.edit", "İş sifarişi redaktə", "maintenance"),
    ("lease.view", "Lease baxış", "leases"),
    ("lease.edit", "Lease redaktə", "leases"),
    ("approval.view", "Təsdiq baxış", "workflows"),
    ("approval.decide", "Təsdiq qərarı", "workflows"),
    ("security.view", "Security portal", "security"),
    ("reception.manage", "Reception idarə (legacy)", "reception"),
    ("reception.view", "Reception baxış", "reception"),
    ("reception.create_visit", "Qonaq qeydiyyatı", "reception"),
    ("reception.check_in", "Check-in", "reception"),
    ("reception.check_out", "Check-out", "reception"),
    ("reception.cancel_visit", "Ziyarət ləğvi", "reception"),
    ("reception.search", "Qonaq axtarışı", "reception"),
    ("reception.export", "Jurnal export", "reception"),
    ("reception.view_sensitive_data", "Seriya nömrəsi tam baxış", "reception"),
    ("reception.override_id", "ID override", "reception"),
    ("resident.view", "Rezident baxış", "residents"),
    ("resident.edit", "Rezident redaktə", "residents"),
    ("resident.export", "Rezident export", "residents"),
    ("residents.export_access", "Giriş/çıxış Excel export", "residents"),
    ("document.view", "Sənəd baxış", "documents"),
    ("document.edit", "Sənəd redaktə", "documents"),
    ("crm.view", "CRM baxış", "crm"),
    ("crm.edit", "CRM redaktə", "crm"),
    ("crm.approve", "CRM təklif təsdiqi", "crm"),
    ("crm.export", "CRM export", "crm"),
    ("finance.view", "Maliyyə baxış", "finance"),
    ("finance.edit", "Maliyyə redaktə", "finance"),
    ("finance.export", "Maliyyə export", "finance"),
    ("warehouse.view", "Anbar baxış", "warehouse"),
    ("warehouse.edit", "Anbar redaktə", "warehouse"),
    ("procurement.view", "Satınalma baxış", "procurement"),
    ("procurement.edit", "Satınalma redaktə", "procurement"),
    ("procurement.approve", "Satınalma təsdiqi", "procurement"),
    ("hr.view", "HR / daxili işçilər baxış", "hr"),
    ("user.view", "İstifadəçi baxış", "accounts"),
    ("user.admin", "İstifadəçi idarəetməsi", "accounts"),
    ("report.view", "Hesabat baxış", "reporting"),
    ("audit.view", "Audit baxış", "audit"),
    ("announcement.publish", "Elan nəşri", "comms"),
]

_ALL_CODES = [p[0] for p in DEFAULT_PERMISSIONS]

# Mutate / sensitive codes Management must not get via catalog (RO hub).
# announcement.publish stays grant-only in RolePermission; can_publish_announcement
# still allows MANAGEMENT by role (product).
_MANAGEMENT_EXCLUDE = {
    "announcement.publish",
    "crm.edit",
    "ticket.edit",
    "ticket.create",
    "work_order.edit",
    "work_order.create",
    "finance.edit",
    "warehouse.edit",
    "procurement.edit",
    "procurement.approve",
    "reception.create_visit",
    "reception.check_in",
    "reception.check_out",
    "reception.cancel_visit",
    "reception.manage",
    "reception.override_id",
    "space.edit",
    "property.asset.edit",
    "user.admin",
}

_RECEPTION_PERMS = [
    "reception.manage",
    "reception.view",
    "reception.create_visit",
    "reception.check_in",
    "reception.check_out",
    "reception.cancel_visit",
    "reception.search",
    "reception.export",
    "reception.view_sensitive_data",
    "reception.override_id",
    "party.view",
    "document.view",
    "resident.view",
]

ROLE_MATRIX = {
    Role.RECEPTION: _RECEPTION_PERMS,
    Role.SERVICE_DESK: [
        "ticket.view",
        "ticket.create",
        "ticket.edit",
        "ticket.export",
        "work_order.view",
        "work_order.edit",
        "party.view",
        "document.view",
        "lease.view",
        "warehouse.view",
        "resident.view",
        "space.view",
    ],
    Role.PROPERTY_FM: [
        "space.view",
        "space.edit",
        "property.asset.view",
        "property.asset.edit",
        "ticket.view",
        "ticket.create",
        "ticket.edit",
        "ticket.export",
        "work_order.view",
        "work_order.create",
        "work_order.edit",
        "party.view",
        "lease.view",
        "lease.edit",
        "document.view",
        "document.edit",
        "reception.view",
        "reception.search",
        "warehouse.view",
        "warehouse.edit",
        "procurement.view",
        "procurement.edit",
        "procurement.approve",
        "resident.view",
        "resident.edit",
    ],
    Role.SECURITY: [
        "security.view",
        "party.view",
        "resident.view",
        "residents.export_access",
        "resident.export",
        "ticket.view",
        "ticket.edit",  # own-dept mutate (tickets_visible_to / can_mutate_ticket)
    ],
    Role.SALES: [
        "party.view",
        "party.edit",
        "lease.view",
        "lease.edit",
        "document.view",
        "approval.view",
        "space.view",
        "crm.view",
        "crm.edit",
        "crm.export",
        "resident.view",
    ],
    Role.ACCOUNTANT: [
        "party.view",
        "lease.view",
        "document.view",
        "report.view",
        "approval.view",
        "crm.view",
        "finance.view",
        "finance.edit",
        "finance.export",
        "resident.view",
    ],
    # Soft catalog for portal; enforcement still via ResidentPortalMixin + object_scope.
    Role.RESIDENT_USER: ["ticket.view", "ticket.create", "document.view", "party.view"],
    # Management: broad view + approve; mutate excluded (RO hub). Publish allowed (product).
    Role.MANAGEMENT: [c for c in _ALL_CODES if c not in _MANAGEMENT_EXCLUDE],
    Role.ADMIN: list(_ALL_CODES),
}


def seed_rbac_catalog() -> int:
    created = 0
    for code, name, module in DEFAULT_PERMISSIONS:
        obj, was = PermissionCode.objects.get_or_create(
            code=code,
            defaults={"name": name, "module": module},
        )
        if was:
            created += 1
        elif obj.name != name or obj.module != module:
            obj.name = name
            obj.module = module
            obj.save(update_fields=["name", "module"])
    for role, codes in ROLE_MATRIX.items():
        for code in codes:
            perm = PermissionCode.objects.get(code=code)
            RolePermission.objects.get_or_create(role=role, permission=perm)
    return created


def user_has_permission(user, code: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.role == Role.ADMIN:
        return True
    # Explicit RolePermission grant (including extras beyond ROLE_MATRIX).
    if RolePermission.objects.filter(role=user.role, permission__code=code).exists():
        return True
    # In-memory ROLE_MATRIX — SoT for defaults even before seed_rbac_catalog().
    if code in ROLE_MATRIX.get(user.role, []):
        return True
    # Legacy fallback: reception.manage covers granular reception.* except sensitive
    if code.startswith("reception.") and code not in (
        "reception.view_sensitive_data",
        "reception.override_id",
    ):
        if "reception.manage" in ROLE_MATRIX.get(user.role, []):
            return True
        return RolePermission.objects.filter(
            role=user.role, permission__code="reception.manage"
        ).exists()
    # Alias: resident.export ↔ residents.export_access
    role_codes = ROLE_MATRIX.get(user.role, [])
    if code == "resident.export":
        return "residents.export_access" in role_codes or RolePermission.objects.filter(
            role=user.role, permission__code="residents.export_access"
        ).exists()
    if code == "residents.export_access":
        return "resident.export" in role_codes or RolePermission.objects.filter(
            role=user.role, permission__code="resident.export"
        ).exists()
    return False


def require_permission(user, code: str, message: str | None = None) -> None:
    """Raise PermissionDenied with a user-visible message when lacking ``code``."""
    if user_has_permission(user, code):
        return
    raise PermissionDenied(message or _("Bu əməliyyata icazəniz yoxdur."))


def require_any_permission(user, *codes: str, message: str | None = None) -> None:
    if any(user_has_permission(user, c) for c in codes if c):
        return
    raise PermissionDenied(message or _("Bu əməliyyata icazəniz yoxdur."))
