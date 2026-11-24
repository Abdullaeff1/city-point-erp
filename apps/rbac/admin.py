from django.contrib import admin

from apps.rbac.models import PermissionCode, RolePermission, UserPermission


@admin.register(PermissionCode)
class PermissionCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "module")
    search_fields = ("code", "name")


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ("role", "permission")
    list_filter = ("role",)


@admin.register(UserPermission)
class UserPermissionAdmin(admin.ModelAdmin):
    list_display = ("user", "permission", "created_at")
    list_filter = ("permission__code",)
    search_fields = ("user__username", "user__email", "permission__code")
    raw_id_fields = ("user", "permission")
