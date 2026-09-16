from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class ChargeSource(models.TextChoices):
    RENT = "rent", _("Rent")
    SERVICE_CHARGE = "service_charge", _("Service charge")
    PARKING = "parking", _("Parking")
    UTILITY = "utility", _("Utility")
    WORK_ORDER = "work_order", _("Work order")
    ADDITIONAL = "additional", _("Additional")
    PENALTY = "penalty", _("Penalty")


class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    ISSUED = "issued", _("Issued")
    PAID = "paid", _("Paid")
    VOID = "void", _("Void")
    OVERDUE = "overdue", _("Overdue")


class Charge(models.Model):
    party = models.ForeignKey(
        "parties.Party",
        on_delete=models.PROTECT,
        related_name="charges",
    )
    lease = models.ForeignKey(
        "leases.Lease",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="charges",
    )
    space = models.ForeignKey(
        "property.Space",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="charges",
    )
    source = models.CharField(max_length=32, choices=ChargeSource.choices, default=ChargeSource.RENT)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="AZN")
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    invoice = models.ForeignKey(
        "billing.Invoice",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="charges",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.description} ({self.amount})"


class Invoice(models.Model):
    code = models.CharField(max_length=32, unique=True)
    party = models.ForeignKey(
        "parties.Party",
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    lease = models.ForeignKey(
        "leases.Lease",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoices",
    )
    status = models.CharField(
        max_length=16,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.DRAFT,
    )
    issue_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=8, default="AZN")
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-issue_date", "-id"]

    def __str__(self):
        return self.code


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    charge = models.ForeignKey(
        Charge,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoice_lines",
    )
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.invoice_id}:{self.description}"
