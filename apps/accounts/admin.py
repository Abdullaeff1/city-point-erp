from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.urls import reverse

from apps.accounts.invite import create_portal_invite, send_invite_email
from apps.accounts.models import PortalInvite, Role, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "username", "role", "resident_company", "must_set_password", "is_active")
    list_filter = ("role", "is_active", "must_set_password")
    search_fields = ("email", "username")
    ordering = ("email",)
    actions = ("send_portal_invite",)
    fieldsets = BaseUserAdmin.fieldsets + (
        ("City Point", {"fields": ("role", "resident_company", "must_set_password")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "username",
                    "password1",
                    "password2",
                    "role",
                    "resident_company",
                    "must_set_password",
                ),
            },
        ),
    )

    @admin.action(description="Portal dəvəti göndər (email)")
    def send_portal_invite(self, request, queryset):
        sent = 0
        for user in queryset:
            if user.role != Role.RESIDENT_USER:
                messages.warning(request, f"{user.email}: yalnız resident_user dəvət oluna bilər.")
                continue
            if not user.resident_company_id:
                messages.warning(request, f"{user.email}: resident_company təyin olunmayıb.")
                continue
            raw = create_portal_invite(user=user, invited_by=request.user)
            path = reverse("accounts:invite_accept", kwargs={"token": raw})
            absolute = request.build_absolute_uri(path)
            try:
                send_invite_email(user=user, absolute_url=absolute)
                sent += 1
            except Exception as exc:  # noqa: BLE001 — surface mail errors in admin
                messages.error(request, f"{user.email}: email göndərilmədi ({exc}). Link: {absolute}")
        if sent:
            messages.success(request, f"{sent} dəvət email göndərildi.")


@admin.register(PortalInvite)
class PortalInviteAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "expires_at", "used_at", "invited_by")
    list_filter = ("used_at",)
    search_fields = ("user__email",)
    readonly_fields = ("user", "token_hash", "created_at", "expires_at", "used_at", "invited_by")

    def has_add_permission(self, request):
        return False
