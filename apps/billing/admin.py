"""Billing Django Admin — financial records are service-owned; Admin is read-only for cash/AR integrity."""

from django.contrib import admin

from apps.billing.models import Charge, Invoice, InvoiceLine, Payment


class _ReadOnlyAdminMixin:
    """Deny Admin mutations; preserve changelist/detail GET for authorized staff."""

    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        # Override default (view==change) so read-only list/detail remains available.
        return bool(request.user and request.user.is_active and request.user.is_staff)


class InvoiceLineInline(_ReadOnlyAdminMixin, admin.TabularInline):
    model = InvoiceLine
    extra = 0
    can_delete = False
    show_change_link = True
    readonly_fields = ("invoice", "charge", "description", "amount")


@admin.register(Charge)
class ChargeAdmin(_ReadOnlyAdminMixin, admin.ModelAdmin):
    """Charges are created by lease/billing services — Admin invent/edit is a pilot-critical bypass."""

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
    readonly_fields = (
        "party",
        "source",
        "description",
        "amount",
        "currency",
        "lease",
        "space",
        "invoice",
        "work_order",
        "period_start",
        "period_end",
        "created_at",
    )


@admin.register(Invoice)
class InvoiceAdmin(_ReadOnlyAdminMixin, admin.ModelAdmin):
    """Invoice status/total must only move via confirm/record_payment/void services."""

    list_display = ("code", "party", "lease", "status", "issue_date", "due_date", "total", "currency")
    list_filter = ("status", "currency")
    search_fields = ("code", "party__legal_name")
    inlines = [InvoiceLineInline]
    readonly_fields = (
        "code",
        "party",
        "lease",
        "status",
        "issue_date",
        "due_date",
        "currency",
        "total",
        "notes",
    )


@admin.register(InvoiceLine)
class InvoiceLineAdmin(_ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("invoice", "charge", "description", "amount")
    readonly_fields = ("invoice", "charge", "description", "amount")


@admin.register(Payment)
class PaymentAdmin(_ReadOnlyAdminMixin, admin.ModelAdmin):
    """Payments only via record_payment after APPROVED finance.payment."""

    list_display = ("invoice", "amount", "currency", "paid_at", "method", "reference")
    list_filter = ("method",)
    search_fields = ("reference", "invoice__code")
    readonly_fields = (
        "invoice",
        "party",
        "amount",
        "currency",
        "paid_at",
        "method",
        "reference",
        "notes",
        "created_at",
    )
