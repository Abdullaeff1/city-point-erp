from django.contrib import admin

from apps.billing.models import Charge, Invoice, InvoiceLine


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0


@admin.register(Charge)
class ChargeAdmin(admin.ModelAdmin):
    list_display = (
        "party",
        "source",
        "description",
        "amount",
        "currency",
        "lease",
        "invoice",
        "created_at",
    )
    list_filter = ("source", "currency")
    search_fields = ("description", "party__legal_name")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("code", "party", "lease", "status", "issue_date", "due_date", "total", "currency")
    list_filter = ("status", "currency")
    search_fields = ("code", "party__legal_name")
    inlines = [InvoiceLineInline]


@admin.register(InvoiceLine)
class InvoiceLineAdmin(admin.ModelAdmin):
    list_display = ("invoice", "charge", "description", "amount")
