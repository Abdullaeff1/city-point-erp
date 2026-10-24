from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class StockMovementType(models.TextChoices):
    RECEIPT = "receipt", _("Receipt")
    ISSUE = "issue", _("Issue")
    RETURN = "return", _("Return")
    TRANSFER = "transfer", _("Transfer")
    ADJUSTMENT = "adjustment", _("Adjustment")
    RESERVATION = "reservation", _("Reservation")
    RELEASE = "release", _("Release")


class Warehouse(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)

    def __str__(self):
        return self.code


class Bin(models.Model):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="bins")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=120, blank=True)

    class Meta:
        unique_together = ("warehouse", "code")

    def __str__(self):
        return f"{self.warehouse.code}:{self.code}"


class SKU(models.Model):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    unit = models.CharField(max_length=16, default="pcs")
    reorder_level = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return self.code


class Stock(models.Model):
    sku = models.ForeignKey(SKU, on_delete=models.CASCADE, related_name="stocks")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="stocks")
    bin = models.ForeignKey(
        Bin,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stocks",
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    class Meta:
        unique_together = ("sku", "warehouse", "bin")

    def __str__(self):
        return f"{self.sku.code} @ {self.warehouse.code}"


class StockMovement(models.Model):
    sku = models.ForeignKey(SKU, on_delete=models.PROTECT, related_name="movements")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=24, choices=StockMovementType.choices)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    reference = models.CharField(max_length=128, blank=True)
    work_order = models.ForeignKey(
        "maintenance.WorkOrder",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_movements",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.movement_type}:{self.sku_id}:{self.quantity}"


class IssueStatus(models.TextChoices):
    OPEN = "open", _("Açıq")
    ISSUED = "issued", _("Çıxış təsdiqlənib")


class WarehouseIssue(models.Model):
    """Open pick document. Stock moves only after the warehouse confirms actual qty."""

    code = models.CharField(max_length=32, unique=True)
    work_order = models.ForeignKey(
        "maintenance.WorkOrder",
        on_delete=models.PROTECT,
        related_name="warehouse_issues",
    )
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="issues")
    status = models.CharField(max_length=16, choices=IssueStatus.choices, default=IssueStatus.OPEN)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="warehouse_issue_requests",
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="warehouse_issues_confirmed",
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code


class WarehouseIssueLine(models.Model):
    issue = models.ForeignKey(WarehouseIssue, on_delete=models.CASCADE, related_name="lines")
    sku = models.ForeignKey(SKU, on_delete=models.PROTECT, related_name="issue_lines")
    requested_qty = models.DecimalField(max_digits=14, decimal_places=3)
    issued_qty = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.issue_id}:{self.sku_id}"
