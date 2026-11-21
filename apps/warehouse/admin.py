from django.contrib import admin

from apps.warehouse.models import (
    SKU,
    Bin,
    Stock,
    StockMovement,
    Stocktake,
    StocktakeLine,
    Warehouse,
)


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(Bin)
class BinAdmin(admin.ModelAdmin):
    list_display = ("warehouse", "code", "name")
    search_fields = ("code", "name")


@admin.register(SKU)
class SKUAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "unit", "reorder_level")
    search_fields = ("code", "name")


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ("sku", "warehouse", "bin", "quantity")
    list_filter = ("warehouse",)


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("sku", "warehouse", "movement_type", "quantity", "reference", "work_order", "created_at")
    list_filter = ("movement_type", "warehouse")


class StocktakeLineInline(admin.TabularInline):
    model = StocktakeLine
    extra = 0
    readonly_fields = (
        "sku",
        "bin",
        "unit",
        "baseline_qty",
        "expected_qty",
        "counted_qty",
        "variance_qty",
        "recount_required",
        "activity_after_count",
        "adjustment_movement",
    )


@admin.register(Stocktake)
class StocktakeAdmin(admin.ModelAdmin):
    list_display = ("code", "warehouse", "status", "started_at", "completed_at", "posted_at")
    list_filter = ("status", "warehouse")
    search_fields = ("code",)
    inlines = [StocktakeLineInline]
