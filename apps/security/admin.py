from django.contrib import admin

from apps.security.models import (
    FloorPatrolMark,
    FloorPatrolRound,
    FloorPatrolSheet,
    SecurityDevice,
    SecurityDevicePin,
    SecurityFloorPlan,
    SecurityFloorPlanRevision,
)


class RevisionInline(admin.TabularInline):
    model = SecurityFloorPlanRevision
    extra = 0
    readonly_fields = (
        "revision_number",
        "source_format",
        "conversion_status",
        "checksum",
        "uploaded_at",
        "converted_at",
        "is_active",
    )
    can_delete = False


@admin.register(SecurityFloorPlan)
class SecurityFloorPlanAdmin(admin.ModelAdmin):
    list_display = ("title", "floor", "category", "is_active", "updated_at")
    list_filter = ("category", "is_active")
    search_fields = ("title",)
    inlines = [RevisionInline]


@admin.register(SecurityFloorPlanRevision)
class SecurityFloorPlanRevisionAdmin(admin.ModelAdmin):
    list_display = (
        "plan",
        "revision_number",
        "source_format",
        "conversion_status",
        "is_active",
        "uploaded_at",
    )
    list_filter = ("conversion_status", "source_format", "is_active")
    readonly_fields = ("checksum", "converted_at", "uploaded_at")


@admin.register(SecurityDevice)
class SecurityDeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "device_type", "ip_address", "status", "updated_at")
    list_filter = ("device_type", "status")
    search_fields = ("name", "ip_address", "location_note")


@admin.register(SecurityDevicePin)
class SecurityDevicePinAdmin(admin.ModelAdmin):
    list_display = ("device", "revision", "x_pct", "y_pct", "updated_at")
    list_filter = ("revision__plan",)


class PatrolRoundInline(admin.TabularInline):
    model = FloorPatrolRound
    extra = 0


@admin.register(FloorPatrolSheet)
class FloorPatrolSheetAdmin(admin.ModelAdmin):
    list_display = ("night_date", "status", "updated_at")
    list_filter = ("status",)
    inlines = [PatrolRoundInline]


@admin.register(FloorPatrolMark)
class FloorPatrolMarkAdmin(admin.ModelAdmin):
    list_display = ("sheet", "floor_code", "row_index", "inspector_name")
    list_filter = ("floor_code",)
