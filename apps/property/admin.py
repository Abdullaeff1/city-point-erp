from django.contrib import admin

from apps.property.models import Asset, Building, Contractor, Floor, Space


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("code", "name")


@admin.register(Floor)
class FloorAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "building")


@admin.register(Space)
class SpaceAdmin(admin.ModelAdmin):
    list_display = ("code", "resident", "area_m2", "occupancy", "cost_center")
    search_fields = ("code",)


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("name", "space", "asset_code")


@admin.register(Contractor)
class ContractorAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_email")
