from django.contrib import admin

from apps.rbac.models import PermissionCode, RolePermission


@admin.register(PermissionCode)
class PermissionCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "module")
    search_fields = ("code", "name")


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ("role", "permission")
    list_filter = ("role",)
