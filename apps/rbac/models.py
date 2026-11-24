from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Role


class PermissionCode(models.Model):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    module = models.CharField(max_length=64, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["module", "code"]

    def __str__(self):
        return self.code


class RolePermission(models.Model):
    role = models.CharField(max_length=32, choices=Role.choices, db_index=True)
    permission = models.ForeignKey(PermissionCode, on_delete=models.CASCADE, related_name="role_grants")

    class Meta:
        unique_together = ("role", "permission")

    def __str__(self):
        return f"{self.role}:{self.permission_id}"


class UserPermission(models.Model):
    """Explicit per-user grant (e.g. designated Təchizat rəhbəri = supply.head)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_permissions_rbac",
    )
    permission = models.ForeignKey(
        PermissionCode, on_delete=models.CASCADE, related_name="user_grants"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "permission")

    def __str__(self):
        return f"{self.user_id}:{self.permission_id}"
