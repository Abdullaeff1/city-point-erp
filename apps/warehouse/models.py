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
    reserved_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    class Meta:
        unique_together = ("sku", "warehouse", "bin")

    def __str__(self):
        return f"{self.sku.code} @ {self.warehouse.code}"

    @property
    def available_quantity(self):
        from decimal import Decimal

        on_hand = self.quantity or Decimal("0")
        reserved = self.reserved_quantity or Decimal("0")
        avail = on_hand - reserved
        return avail if avail > 0 else Decimal("0")


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


class StocktakeStatus(models.TextChoices):
    OPEN = "open", _("Açıq")
    COMPLETED = "completed", _("Bitirilib")
    POSTING = "posting", _("Düzəlişlər tətbiq olunur")
    POSTED = "posted", _("Düzəlişlər tətbiq olunub")
    CANCELLED = "cancelled", _("Ləğv")


class Stocktake(models.Model):
    """Warehouse physical count session with historical variance report."""

    code = models.CharField(max_length=32, unique=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="stocktakes")
    status = models.CharField(
        max_length=16, choices=StocktakeStatus.choices, default=StocktakeStatus.OPEN
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stocktakes_started",
    )
    started_at = models.DateTimeField(default=timezone.now, editable=False)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stocktakes_completed",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stocktakes_posted",
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return self.code


class StocktakeLine(models.Model):
    """
    One countable balance key: warehouse + SKU (+ bin when used).

    expected_qty is the system on-hand captured when the physical count is saved
    (not a frozen session-start snapshot alone). counted_qty null = uncounted;
    never coerce an empty form field to zero.
    """

    stocktake = models.ForeignKey(Stocktake, on_delete=models.CASCADE, related_name="lines")
    sku = models.ForeignKey(SKU, on_delete=models.PROTECT, related_name="stocktake_lines")
    bin = models.ForeignKey(
        Bin,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stocktake_lines",
    )
    unit = models.CharField(max_length=16, default="pcs")
    # On-hand at session start (evidence / progress only).
    baseline_qty = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    baseline_at = models.DateTimeField(default=timezone.now)
    # System on-hand when the operator saved the physical quantity.
    expected_qty = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    counted_qty = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    variance_qty = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    counted_at = models.DateTimeField(null=True, blank=True)
    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stocktake_lines_counted",
    )
    recount_required = models.BooleanField(default=False)
    activity_after_count = models.BooleanField(
        default=False,
        help_text=_("Balance-affecting movement after counted_at; review before posting."),
    )
    adjustment_movement = models.ForeignKey(
        StockMovement,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stocktake_lines",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("stocktake", "sku", "bin")
        ordering = ["sku__code"]

    def __str__(self):
        return f"{self.stocktake_id}:{self.sku_id}"

    @property
    def is_counted(self) -> bool:
        return self.counted_qty is not None

    @property
    def variance_kind(self) -> str:
        if self.counted_qty is None:
            return "uncounted"
        if self.variance_qty is None:
            return "uncounted"
        if self.variance_qty == 0:
            return "match"
        if self.variance_qty > 0:
            return "surplus"
        return "shortage"
