from django.contrib import admin

from apps.residents.models import AccessEvent, ResidentCompany, ResidentEmployee


@admin.register(ResidentCompany)
class ResidentCompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "status", "portal_active")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ResidentEmployee)
class ResidentEmployeeAdmin(admin.ModelAdmin):
    list_display = ("full_name", "company", "card_number", "is_active")


@admin.register(AccessEvent)
class AccessEventAdmin(admin.ModelAdmin):
    list_display = ("employee", "event_type", "occurred_at")
