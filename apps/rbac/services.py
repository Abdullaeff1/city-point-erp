from apps.accounts.models import Role
from apps.rbac.models import PermissionCode, RolePermission

# Foundation catalog — extend per scope; Admin/Management get all via bypass.
DEFAULT_PERMISSIONS = [
    ("party.view", "Party baxış", "parties"),
    ("party.edit", "Party redaktə", "parties"),
    ("space.view", "Sahə baxış", "property"),
    ("space.edit", "Sahə redaktə", "property"),
    ("ticket.view", "Ticket baxış", "tickets"),
    ("ticket.edit", "Ticket redaktə", "tickets"),
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
    ("document.view", "Sənəd baxış", "documents"),
    ("document.edit", "Sənəd redaktə", "documents"),
    ("report.view", "Hesabat baxış", "reporting"),
    ("audit.view", "Audit baxış", "audit"),
]

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
]

ROLE_MATRIX = {
    Role.RECEPTION: _RECEPTION_PERMS,
    Role.SERVICE_DESK: ["ticket.view", "ticket.edit", "party.view", "document.view"],
    Role.PROPERTY_FM: [
        "space.view",
        "space.edit",
        "ticket.view",
        "ticket.edit",
        "party.view",
        "lease.view",
        "document.view",
        "reception.view",
        "reception.search",
    ],
    Role.SECURITY: ["security.view", "party.view"],
    Role.MANAGEMENT: [p[0] for p in DEFAULT_PERMISSIONS],
    Role.ADMIN: [p[0] for p in DEFAULT_PERMISSIONS],
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
    if user.role in (Role.ADMIN, Role.MANAGEMENT):
        return True
    if RolePermission.objects.filter(role=user.role, permission__code=code).exists():
        return True
    # Legacy fallback: reception.manage covers granular reception.* except sensitive
    if code.startswith("reception.") and code not in (
        "reception.view_sensitive_data",
        "reception.override_id",
    ):
        return RolePermission.objects.filter(
            role=user.role, permission__code="reception.manage"
        ).exists()
    return False
