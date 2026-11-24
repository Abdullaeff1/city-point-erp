"""Supplier (AP) invoices — finance-owned, matched to procurement PO lines."""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class SupplierInvoiceStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    MATCHED = "matched", _("Matched")
    HOLD = "hold", _("Hold")
    RECOGNIZED = "recognized", _("Recognized")
    VOID = "void", _("Void")


class SupplierInvoice(models.Model):
    code = models.CharField(max_length=32, unique=True)
    supplier_party = models.ForeignKey(
        "parties.Party",
        on_delete=models.PROTECT,
        related_name="supplier_invoices",
    )
    supplier_invoice_no = models.CharField(max_length=64)
    invoice_date = models.DateField(default=timezone.localdate)
    currency = models.CharField(max_length=8, default="AZN")
    status = models.CharField(
        max_length=16,
        choices=SupplierInvoiceStatus.choices,
        default=SupplierInvoiceStatus.DRAFT,
    )
    notes = models.TextField(blank=True)
    external_ref = models.CharField(max_length=128, blank=True)
    hold_reason = models.CharField(max_length=255, blank=True)
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="supplier_invoices",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_supplier_invoices",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-invoice_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["supplier_party", "supplier_invoice_no"],
                name="uniq_supplier_invoice_no_per_party",
            ),
        ]

    def __str__(self):
        return self.code


class SupplierInvoiceLine(models.Model):
    supplier_invoice = models.ForeignKey(
        SupplierInvoice, on_delete=models.CASCADE, related_name="lines"
    )
    po_line = models.ForeignKey(
        "procurement.POLine",
        on_delete=models.PROTECT,
        related_name="supplier_invoice_lines",
    )
    description = models.CharField(max_length=255, blank=True)
    qty_invoiced = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    # Snapshot at last validate (for display when HOLD)
    variance_qty = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.supplier_invoice_id}:{self.po_line_id}"

    @property
    def line_net(self):
        from decimal import Decimal

        return (self.qty_invoiced * self.unit_price).quantize(Decimal("0.01"))

    @property
    def line_vat(self):
        from decimal import Decimal

        if not self.tax_rate:
            return Decimal("0.00")
        return (self.line_net * self.tax_rate / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def line_gross(self):
        return self.line_net + self.line_vat


class SupplierPayment(models.Model):
    """AP settlement — distinct from resident AR Payment (billing.Payment)."""

    supplier_invoice = models.ForeignKey(
        SupplierInvoice, on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=8, default="AZN")
    paid_at = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=32, blank=True, default="bank")
    reference = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)
    approval_request = models.ForeignKey(
        "workflows.ApprovalRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="supplier_payments",
    )
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="supplier_payments",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-paid_at", "-id"]

    def __str__(self):
        return f"SPAY-{self.pk}:{self.amount}"
