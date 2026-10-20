from django.contrib import admin

from apps.maintenance.models import Inspection, MaintenancePlan


@admin.register(MaintenancePlan)
class MaintenancePlanAdmin(admin.ModelAdmin):
    list_display = ("name", "frequency", "asset", "space", "next_due", "is_active")
    list_filter = ("frequency", "is_active")


@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    list_display = ("plan", "space", "inspected_at", "result")
    list_filter = ("result",)
