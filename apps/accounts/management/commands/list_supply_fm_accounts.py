"""List Təchizat (Service Desk) accounts and designated supply.head holders."""

from django.core.management.base import BaseCommand

from apps.accounts.models import Role, User
from apps.accounts.supply import is_supply_head
from apps.rbac.models import UserPermission
from apps.rbac.services import user_has_permission


class Command(BaseCommand):
    help = (
        "List Təchizat şöbəsi (service_desk) accounts and designated supply.head holders. "
        "Does not change roles or open work."
    )

    def handle(self, *args, **options):
        self.stdout.write("=== Təchizat rəhbəri (supply.head) ===")
        heads = (
            UserPermission.objects.filter(permission__code="supply.head")
            .select_related("user")
            .order_by("user_id")
        )
        if not heads.exists():
            self.stdout.write(self.style.WARNING("  (yoxdur — City Point təsdiqi lazımdır)"))
        for row in heads:
            u = row.user
            self.stdout.write(
                f"  {u.email} | {u.username} | role={u.role} | active={u.is_active}"
            )

        self.stdout.write("\n=== Təchizat şöbəsi (service_desk) ===")
        staff = User.objects.filter(role=Role.SERVICE_DESK).order_by("id")
        for u in staff:
            flag = "HEAD" if is_supply_head(u) else "operator"
            self.stdout.write(
                f"  id={u.pk} | {u.email} | {u.username} | active={u.is_active} | "
                f"staff={u.is_staff} | {flag} | "
                f"space.edit={user_has_permission(u, 'space.edit')} | "
                f"procurement.edit={user_has_permission(u, 'procurement.edit')}"
            )
        legacy = User.objects.filter(role="property_fm").count()
        if legacy:
            self.stdout.write(
                self.style.WARNING(
                    f"\nQalıq property_fm istifadəçi: {legacy} — seed_rbac_catalog / migrate ilə service_desk-ə keçin."
                )
            )
