from django.contrib import admin, messages
from django.db.models import ProtectedError

from apps.residents.models import AccessEvent, ResidentCompany, ResidentEmployee


@admin.register(ResidentCompany)
class ResidentCompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "status", "portal_active", "is_internal")
    list_filter = ("status", "portal_active", "is_internal")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ResidentEmployee)
class ResidentEmployeeAdmin(admin.ModelAdmin):
    list_display = ("full_name", "company", "card_number", "is_active", "deactivated_at")
    list_filter = ("is_active", "company")
    search_fields = ("full_name", "card_number")
    readonly_fields = ("deactivated_at",)

    def delete_model(self, request, obj):
        try:
            super().delete_model(request, obj)
        except ProtectedError:
            messages.error(
                request,
                "Bu işçinin giriş/çıxış tarixçəsi var — silinə bilməz. is_active=False edin.",
            )

    def delete_queryset(self, request, queryset):
        try:
            super().delete_queryset(request, queryset)
        except ProtectedError:
            messages.error(
                request,
                "Seçilmiş işçilərin giriş/çıxış tarixçəsi var — hard delete qadağandır.",
            )


@admin.register(AccessEvent)
class AccessEventAdmin(admin.ModelAdmin):
    list_display = ("employee", "employee_name", "event_type", "occurred_at", "card_number")
    list_filter = ("event_type",)
    search_fields = ("employee_name", "card_number", "employee__full_name")
    readonly_fields = (
        "employee",
        "event_type",
        "occurred_at",
        "employee_name",
        "card_number",
        "axtrax_employee_id",
    )
    date_hierarchy = "occurred_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
