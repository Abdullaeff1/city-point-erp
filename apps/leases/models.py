from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import UUIDPrimaryModel


class LeaseStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    NEGOTIATION = "negotiation", _("Negotiation")
    APPROVED = "approved", _("Approved")
    SIGNED = "signed", _("Signed")
    ACTIVE = "active", _("Active")
    EXPIRING = "expiring", _("Expiring")
    RENEWED = "renewed", _("Renewed")
    AMENDED = "amended", _("Amended")
    TERMINATED = "terminated", _("Terminated")


class Lease(UUIDPrimaryModel):
    code = models.CharField(max_length=64, unique=True)
    party = models.ForeignKey(
        "parties.Party",
        on_delete=models.PROTECT,
        related_name="leases",
    )
    space = models.ForeignKey(
        "property.Space",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="leases",
    )
    status = models.CharField(
        max_length=24,
        choices=LeaseStatus.choices,
        default=LeaseStatus.DRAFT,
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    rent = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="AZN")
    deposit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    service_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    parent_lease = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="amendments",
    )
    billing_active = models.BooleanField(default=False)
    portal_eligible = models.BooleanField(default=False)
    access_eligible = models.BooleanField(default=False)
    billing_frequency = models.CharField(
        max_length=16,
        choices=[
            ("monthly", "Monthly"),
            ("quarterly", "Quarterly"),
            ("yearly", "Yearly"),
            ("once", "Once"),
        ],
        default="monthly",
    )
    notes = models.TextField(blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    terminated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code


class LeaseLine(models.Model):
    lease = models.ForeignKey(Lease, on_delete=models.CASCADE, related_name="lines")
    space = models.ForeignKey(
        "property.Space",
        on_delete=models.PROTECT,
        related_name="lease_lines",
    )
    area_m2 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    rent_share = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.lease_id}:{self.space_id}"
