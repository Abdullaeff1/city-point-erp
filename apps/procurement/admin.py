from django.contrib import admin

from apps.procurement.models import (
    GoodsReceiptOperation,
    POLine,
    PRLine,
    PurchaseApprovalLimit,
    PurchaseOrder,
    PurchaseRequest,
    RFQ,
    RFQQuote,
)


class PRLineInline(admin.TabularInline):
    model = PRLine
    extra = 0


class POLineInline(admin.TabularInline):
    model = POLine
    extra = 0


class RFQQuoteInline(admin.TabularInline):
    model = RFQQuote
    extra = 0


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "status", "source", "requested_by", "created_at")
    list_filter = ("status", "source")
    search_fields = ("code", "title")
    inlines = [PRLineInline]


@admin.register(PRLine)
class PRLineAdmin(admin.ModelAdmin):
    list_display = ("pr", "sku", "description", "qty", "unit")


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("code", "supplier_party", "status", "pr", "ordered_at")
    list_filter = ("status",)
    search_fields = ("code",)
    inlines = [POLineInline]


@admin.register(POLine)
class POLineAdmin(admin.ModelAdmin):
    list_display = ("po", "description", "sku", "qty", "unit_price", "received_qty")


@admin.register(RFQ)
class RFQAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "pr", "created_at")
    search_fields = ("code", "title")
    inlines = [RFQQuoteInline]


@admin.register(RFQQuote)
class RFQQuoteAdmin(admin.ModelAdmin):
    list_display = ("rfq", "supplier_party", "unit_price", "lead_time_days", "is_selected")
    list_filter = ("is_selected",)


@admin.register(PurchaseApprovalLimit)
class PurchaseApprovalLimitAdmin(admin.ModelAdmin):
    list_display = ("role", "max_amount", "is_active")
    list_filter = ("is_active",)
    list_display_links = ("role",)
    fields = ("role", "max_amount", "is_active")


@admin.register(GoodsReceiptOperation)
class GoodsReceiptOperationAdmin(admin.ModelAdmin):
    list_display = ("operation_key", "po", "warehouse", "mode", "actor", "created_at")
    list_filter = ("mode",)
    search_fields = ("operation_key", "po__code")
    readonly_fields = (
        "operation_key",
        "po",
        "warehouse",
        "actor",
        "mode",
        "payload_fingerprint",
        "lines_json",
        "created_at",
    )
