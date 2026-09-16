from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class LeadSource(models.TextChoices):
    WEBSITE = "website", _("Website")
    PHONE = "phone", _("Phone")
    EMAIL = "email", _("Email")
    WALK_IN = "walk_in", _("Walk-in")
    REFERRAL = "referral", _("Referral")
    MANUAL = "manual", _("Manual")
    OTHER = "other", _("Other")


class LeadStatus(models.TextChoices):
    NEW = "new", _("New")
    QUALIFIED = "qualified", _("Qualified")
    DISQUALIFIED = "disqualified", _("Disqualified")
    CONVERTED = "converted", _("Converted")


class OpportunityStatus(models.TextChoices):
    OPEN = "open", _("Open")
    WON = "won", _("Won")
    LOST = "lost", _("Lost")


class OfferStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SENT = "sent", _("Sent")
    NEGOTIATION = "negotiation", _("Negotiation")
    ACCEPTED = "accepted", _("Accepted")
    REJECTED = "rejected", _("Rejected")


class Lead(models.Model):
    full_name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=64, blank=True)
    company_name = models.CharField(max_length=200, blank=True)
    source = models.CharField(max_length=32, choices=LeadSource.choices, default=LeadSource.MANUAL)
    status = models.CharField(max_length=24, choices=LeadStatus.choices, default=LeadStatus.NEW)
    message = models.TextField(blank=True)
    interested_space = models.ForeignKey(
        "property.Space",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="leads",
    )
    party = models.ForeignKey(
        "parties.Party",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="leads",
    )
    external_id = models.CharField(max_length=128, blank=True, null=True, unique=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.full_name


class Opportunity(models.Model):
    lead = models.ForeignKey(
        Lead,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="opportunities",
    )
    party = models.ForeignKey(
        "parties.Party",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="opportunities",
    )
    title = models.CharField(max_length=200)
    status = models.CharField(
        max_length=16,
        choices=OpportunityStatus.choices,
        default=OpportunityStatus.OPEN,
    )
    expected_area = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "opportunities"

    def __str__(self):
        return self.title


class Offer(models.Model):
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="offers")
    space = models.ForeignKey(
        "property.Space",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="offers",
    )
    party = models.ForeignKey(
        "parties.Party",
        on_delete=models.PROTECT,
        related_name="offers",
    )
    status = models.CharField(max_length=24, choices=OfferStatus.choices, default=OfferStatus.DRAFT)
    rent_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valid_until = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    lease = models.ForeignKey(
        "leases.Lease",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_offers",
    )

    def __str__(self):
        return f"{self.opportunity_id}:{self.status}"
