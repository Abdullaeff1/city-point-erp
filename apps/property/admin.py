from django.contrib import admin

from apps.property.models import (
    Asset,
    Building,
    BuildingAsset,
    Contractor,
    Floor,
    MeterReading,
    ParkingAssignment,
    ParkingSpot,
    ParkingZone,
    Space,
    SpaceDrawing,
    SpaceDrawingAccessRequest,
    UtilityMeter,
)


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("code", "name")


@admin.register(Floor)
class FloorAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "building")


@admin.register(Space)
class SpaceAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "resident",
        "area_m2",
        "rentable_area_m2",
        "occupancy",
        "commercial_status",
        "operational_status",
        "is_public",
        "cost_center",
    )
    list_filter = ("commercial_status", "operational_status", "occupancy", "is_public")
    search_fields = ("code",)


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("name", "space", "asset_code")


@admin.register(BuildingAsset)
class BuildingAssetAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "kind",
        "category",
        "floor",
        "location",
        "last_inspected_on",
        "next_inspection_on",
        "is_active",
    )
    list_filter = ("kind", "category", "is_active")
    search_fields = ("name", "code", "location")


@admin.register(Contractor)
class ContractorAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_email", "party")


@admin.register(ParkingZone)
class ParkingZoneAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "building")
    search_fields = ("code", "name")


@admin.register(ParkingSpot)
class ParkingSpotAdmin(admin.ModelAdmin):
    list_display = ("zone", "code", "is_active")
    list_filter = ("is_active", "zone")


@admin.register(ParkingAssignment)
class ParkingAssignmentAdmin(admin.ModelAdmin):
    list_display = ("spot", "party", "vehicle_plate", "assignment_type", "start_date", "end_date")
    list_filter = ("assignment_type",)


@admin.register(UtilityMeter)
class UtilityMeterAdmin(admin.ModelAdmin):
    list_display = ("meter_code", "space", "utility_type", "unit")
    list_filter = ("utility_type",)
    search_fields = ("meter_code", "space__code")


@admin.register(MeterReading)
class MeterReadingAdmin(admin.ModelAdmin):
    list_display = ("meter", "reading", "read_at")


@admin.register(SpaceDrawing)
class SpaceDrawingAdmin(admin.ModelAdmin):
    list_display = ("original_name", "space", "kind", "package_id", "uploaded_by", "created_at")
    list_filter = ("kind",)
    search_fields = ("original_name", "space__code", "package_id")
    autocomplete_fields = ("space", "uploaded_by")
    readonly_fields = ("created_at",)


@admin.register(SpaceDrawingAccessRequest)
class SpaceDrawingAccessRequestAdmin(admin.ModelAdmin):
    list_display = ("drawing", "user", "status", "approved_by", "expires_at", "created_at")
    list_filter = ("status",)
    search_fields = ("user__email", "drawing__original_name", "drawing__space__code")
    autocomplete_fields = ("user", "drawing", "approved_by")
    readonly_fields = ("created_at", "decided_at")
