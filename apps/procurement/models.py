from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class PRStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SUBMITTED = "submitted", _("Submitted")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    ORDERED = "ordered", _("Ordered")


class PRSource(models.TextChoices):
    MANUAL = "manual", _("Manual")
    LOW_STOCK = "low_stock", _("Low stock")
    WO = "wo", _("Work order")
    DEPARTMENT = "department", _("Department")


class POStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SENT = "sent", _("Sent")
    PARTIAL = "partial", _("Partial")
    RECEIVED = "received", _("Received")
    CLOSED = "closed", _("Closed")
    CANCELLED = "cancelled", _("Cancelled")


class PurchaseRequest(models.Model):
    code = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=24, choices=PRStatus.choices, default=PRStatus.DRAFT)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_requests",
    )
    source = models.CharField(max_length=24, choices=PRSource.choices, default=PRSource.MANUAL)
    notes = models.TextField(blank=True)
    work_order = models.ForeignKey(
        "maintenance.WorkOrder",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_requests",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code


class PRLine(models.Model):
    pr = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name="lines")
    sku = models.ForeignKey(
        "warehouse.SKU",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pr_lines",
    )
    description = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=14, decimal_places=3, default=1)
    unit = models.CharField(max_length=16, default="pcs")

    def __str__(self):
        return f"{self.pr_id}:{self.description}"


class PurchaseOrder(models.Model):
    code = models.CharField(max_length=32, unique=True)
    supplier_party = models.ForeignKey(
        "parties.Party",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_orders",
    )
    status = models.CharField(max_length=24, choices=POStatus.choices, default=POStatus.DRAFT)
    pr = models.ForeignKey(
        PurchaseRequest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_orders",
    )
    ordered_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.code


class POLine(models.Model):
    po = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    description = models.CharField(max_length=255)
    sku = models.ForeignKey(
        "warehouse.SKU",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="po_lines",
    )
    qty = models.DecimalField(max_digits=14, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    received_qty = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    def __str__(self):
        return f"{self.po_id}:{self.description}"


class RFQ(models.Model):
    code = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=200, blank=True)
    pr = models.ForeignKey(
        PurchaseRequest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rfqs",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = "RFQ"
        verbose_name_plural = "RFQs"

    def __str__(self):
        return self.code


class RFQQuote(models.Model):
    """Supplier quote against an RFQ — compare before creating PO."""

    rfq = models.ForeignKey(RFQ, on_delete=models.CASCADE, related_name="quotes")
    supplier_party = models.ForeignKey(
        "parties.Party",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rfq_quotes",
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="AZN")
    lead_time_days = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    is_selected = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["unit_price", "id"]

    def __str__(self):
        return f"{self.rfq_id}:{self.unit_price}"


class PurchaseApprovalLimit(models.Model):
    """Monetary AZN ceiling a role may approve without Management escalation.

    Tax basis (net/gross/VAT) is not encoded here — Finance must confirm before
    local approval uses quoted totals as spending authority. PR lines currently
    carry no unit price; comparable money appears at RFQ quote / PO line stage.
    """

    role = models.CharField(max_length=32, unique=True)
    max_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text=_("Maksimum məbləğ (AZN). Miqdar deyil."),
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.role}:{self.max_amount} AZN"


class GoodsReceiptOperation(models.Model):
    """Durable idempotency record for a single goods-receipt submission."""

    MODE_FULL = "full"
    MODE_PARTIAL = "partial"
    MODE_CHOICES = (
        (MODE_FULL, _("Full")),
        (MODE_PARTIAL, _("Partial")),
    )

    operation_key = models.CharField(max_length=64, unique=True)
    po = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="receipt_operations",
    )
    warehouse = models.ForeignKey(
        "warehouse.Warehouse",
        on_delete=models.PROTECT,
        related_name="goods_receipt_operations",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="goods_receipt_operations",
    )
    mode = models.CharField(max_length=16, choices=MODE_CHOICES)
    payload_fingerprint = models.CharField(max_length=64)
    lines_json = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.operation_key
