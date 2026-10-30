from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.invite import create_portal_invite, send_invite_email
from apps.accounts.membership import set_user_memberships
from apps.accounts.models import PortalCompanyMembership, PortalInvite, Role, User
from apps.accounts.portal_scope import eligible_companies_qs


class PortalCompanyMembershipForm(forms.ModelForm):
    class Meta:
        model = PortalCompanyMembership
        fields = ("company", "is_active", "is_primary")


class PortalCompanyMembershipInline(admin.TabularInline):
    model = PortalCompanyMembership
    fk_name = "user"
    form = PortalCompanyMembershipForm
    extra = 1
    autocomplete_fields = ("company",)
    fields = ("company", "is_active", "is_primary", "created_at", "created_by")
    readonly_fields = ("created_at", "created_by")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "email",
        "username",
        "role",
        "resident_company",
        "ticket_department",
        "must_set_password",
        "is_active",
    )
    list_filter = ("role", "is_active", "must_set_password", "ticket_department")
    search_fields = ("email", "username")
    ordering = ("email",)
    actions = ("send_portal_invite",)
    autocomplete_fields = ("resident_company", "ticket_department")
    inlines = (PortalCompanyMembershipInline,)
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "City Point",
            {
                "fields": ("role", "resident_company", "ticket_department", "must_set_password"),
                "description": (
                    "resident_company primary üzvlükdən avtomatik sinxronlaşır. "
                    "Şirkət çıxışını aşağıdakı üzvlük cədvəlindən idarə edin."
                ),
            },
        ),
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
                    "ticket_department",
                    "must_set_password",
                ),
            },
        ),
    )
    readonly_fields = ()

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and obj.role == Role.RESIDENT_USER:
            # Prefer membership inline as source of truth; keep FK visible but read-only when editing
            if "resident_company" not in ro:
                ro.append("resident_company")
        return ro

    def save_formset(self, request, form, formset, change):
        if formset.model is PortalCompanyMembership:
            instances = formset.save(commit=False)
            for obj in formset.deleted_objects:
                obj.is_active = False
                obj.is_primary = False
                obj.save(update_fields=["is_active", "is_primary", "updated_at"])
            for obj in instances:
                if obj.pk is None and obj.created_by_id is None:
                    obj.created_by = request.user
                obj.save()
            formset.save_m2m()

            user = form.instance
            if user.role == Role.RESIDENT_USER:
                active = list(
                    PortalCompanyMembership.objects.filter(user=user, is_active=True).select_related(
                        "company"
                    )
                )
                if not active:
                    raise ValidationError("Rezident üçün ən azı bir aktiv şirkət üzvlüyü lazımdır.")
                primaries = [m for m in active if m.is_primary]
                if len(primaries) == 0:
                    active[0].is_primary = True
                    active[0].save(update_fields=["is_primary", "updated_at"])
                    primaries = [active[0]]
                elif len(primaries) > 1:
                    keep = primaries[0]
                    PortalCompanyMembership.objects.filter(user=user, is_active=True).exclude(
                        pk=keep.pk
                    ).update(is_primary=False)
                    primaries = [keep]
                set_user_memberships(
                    user=user,
                    company_ids=[m.company_id for m in active],
                    primary_company_id=primaries[0].company_id,
                    created_by=request.user,
                    replace=True,
                )
            return
        super().save_formset(request, form, formset, change)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # New resident with only FK set (add form) — seed membership
        if obj.role == Role.RESIDENT_USER and obj.resident_company_id:
            if not PortalCompanyMembership.objects.filter(user=obj, is_active=True).exists():
                set_user_memberships(
                    user=obj,
                    company_ids=[obj.resident_company_id],
                    primary_company_id=obj.resident_company_id,
                    created_by=request.user,
                    replace=True,
                )

    @admin.action(description="Portal dəvəti göndər (email)")
    def send_portal_invite(self, request, queryset):
        sent = 0
        for user in queryset:
            if user.role != Role.RESIDENT_USER:
                messages.warning(request, f"{user.email}: yalnız resident_user dəvət oluna bilər.")
                continue
            if not eligible_companies_qs(user).exists() and not user.resident_company_id:
                messages.warning(request, f"{user.email}: aktiv portal şirkəti yoxdur.")
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


@admin.register(PortalCompanyMembership)
class PortalCompanyMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "company", "is_active", "is_primary", "created_at", "created_by")
    list_filter = ("is_active", "is_primary", "company")
    search_fields = ("user__email", "company__name", "company__slug")
    autocomplete_fields = ("user", "company", "created_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(PortalInvite)
class PortalInviteAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "expires_at", "used_at", "invited_by")
    list_filter = ("used_at",)
    search_fields = ("user__email",)
    readonly_fields = ("user", "token_hash", "created_at", "expires_at", "used_at", "invited_by")

    def has_add_permission(self, request):
        return False
