from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class WorkOrderStatus(models.TextChoices):
    OPEN = "open", _("Açıq")
    ASSIGNED = "assigned", _("Təyin edilib")
    IN_PROGRESS = "in_progress", _("İcradadır")
    COMPLETED = "completed", _("Tamamlanıb")
    CANCELLED = "cancelled", _("Ləğv")


class WorkOrderPriority(models.TextChoices):
    LOW = "low", _("Low")
    NORMAL = "normal", _("Normal")
    HIGH = "high", _("High")


class PlanFrequency(models.TextChoices):
    DAILY = "daily", _("Daily")
    WEEKLY = "weekly", _("Weekly")
    MONTHLY = "monthly", _("Monthly")
    QUARTERLY = "quarterly", _("Quarterly")
    YEARLY = "yearly", _("Yearly")
    METER = "meter", _("Meter")


class WorkOrder(models.Model):
    code = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=24,
        choices=WorkOrderStatus.choices,
        default=WorkOrderStatus.OPEN,
    )
    priority = models.CharField(
        max_length=16,
        choices=WorkOrderPriority.choices,
        default=WorkOrderPriority.NORMAL,
    )
    space = models.ForeignKey(
        "property.Space",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_orders",
    )
    asset = models.ForeignKey(
        "property.Asset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_orders",
    )
    ticket = models.ForeignKey(
        "tickets.Ticket",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_orders",
    )
    contractor = models.ForeignKey(
        "property.Contractor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_orders",
    )
    party = models.ForeignKey(
        "parties.Party",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_orders",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_work_orders",
    )
    billable = models.BooleanField(default=False)
    material_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    labor_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    resident_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    scheduled_for = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code


class CostLineKind(models.TextChoices):
    MATERIAL = "material", _("Material")
    LABOR = "labor", _("İşçilik")


class CostLineSource(models.TextChoices):
    MANUAL = "manual", _("Əl ilə")
    WAREHOUSE = "warehouse", _("Anbar")
    PROCUREMENT = "procurement", _("Satınalma")


class WorkOrderCostLine(models.Model):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="cost_lines")
    kind = models.CharField(max_length=16, choices=CostLineKind.choices)
    source = models.CharField(max_length=16, choices=CostLineSource.choices, default=CostLineSource.MANUAL)
    description = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=14, decimal_places=3, default=1)
    unit = models.CharField(max_length=16, default="ədəd")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    warehouse_issue_line = models.OneToOneField(
        "warehouse.WarehouseIssueLine",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cost_line",
    )
    po_line = models.OneToOneField(
        "procurement.POLine",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cost_line",
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["kind", "sort_order", "id"]

    def __str__(self):
        return self.description


class MaintenancePlan(models.Model):
    name = models.CharField(max_length=200)
    frequency = models.CharField(max_length=16, choices=PlanFrequency.choices, default=PlanFrequency.MONTHLY)
    asset = models.ForeignKey(
        "property.Asset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="maintenance_plans",
    )
    space = models.ForeignKey(
        "property.Space",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="maintenance_plans",
    )
    next_due = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Inspection(models.Model):
    plan = models.ForeignKey(
        MaintenancePlan,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="inspections",
    )
    space = models.ForeignKey(
        "property.Space",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="inspections",
    )
    inspected_at = models.DateTimeField(default=timezone.now)
    result = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-inspected_at"]

    def __str__(self):
        return f"Inspection {self.pk} @ {self.inspected_at}"
