"""Assign designated Head of Supply via UserPermission (no hard-coded email)."""

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.rbac.services import grant_user_permission, seed_rbac_catalog, user_has_permission


class Command(BaseCommand):
    help = (
        "Grant supply.head to an existing user by --user-id or --username. "
        "Does not match production accounts by hard-coded email."
    )

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, help="Primary key of the staff user")
        parser.add_argument("--username", type=str, help="Username of the staff user")
        parser.add_argument(
            "--revoke",
            action="store_true",
            help="Remove supply.head from the named user",
        )

    def handle(self, *args, **options):
        seed_rbac_catalog()
        user_id = options.get("user_id")
        username = (options.get("username") or "").strip()
        if bool(user_id) == bool(username):
            raise CommandError("Exactly one of --user-id or --username is required.")
        if user_id:
            user = User.objects.filter(pk=user_id).first()
        else:
            user = User.objects.filter(username=username).first()
        if user is None:
            raise CommandError("User not found.")
        if not user.is_active:
            raise CommandError(f"User {user.username} is inactive.")

        if options.get("revoke"):
            from apps.rbac.models import UserPermission

            deleted, _ = UserPermission.objects.filter(
                user=user, permission__code="supply.head"
            ).delete()
            self.stdout.write(
                self.style.WARNING(
                    f"Revoked supply.head from {user.username} ({user.email}) "
                    f"deleted={deleted}"
                )
            )
            return

        grant_user_permission(user, "supply.head")
        self.stdout.write(
            self.style.SUCCESS(
                f"Granted supply.head → {user.username} | {user.email} | "
                f"role={user.role} | procurement.edit={user_has_permission(user, 'procurement.edit')}"
            )
        )
