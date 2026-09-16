from django.contrib import admin

from apps.property.models import (
    Asset,
    Building,
    Contractor,
    Floor,
    MeterReading,
    ParkingAssignment,
    ParkingSpot,
    ParkingZone,
    Space,
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
