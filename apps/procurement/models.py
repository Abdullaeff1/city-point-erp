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


# RFQ stub — placeholder model for future RFQ workflow
class RFQ(models.Model):
    code = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = "RFQ"
        verbose_name_plural = "RFQs"

    def __str__(self):
        return self.code
