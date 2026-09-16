from django.contrib import admin

from apps.procurement.models import POLine, PRLine, PurchaseOrder, PurchaseRequest, RFQ


class PRLineInline(admin.TabularInline):
    model = PRLine
    extra = 0


class POLineInline(admin.TabularInline):
    model = POLine
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
    list_display = ("code", "title", "created_at")
    search_fields = ("code", "title")
