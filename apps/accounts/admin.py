from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "username", "role", "resident_company", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("email", "username")
    ordering = ("email",)
    fieldsets = BaseUserAdmin.fieldsets + (
        ("City Point", {"fields": ("role", "resident_company")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "username", "password1", "password2", "role", "resident_company"),
            },
        ),
    )
