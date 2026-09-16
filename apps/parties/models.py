from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import UUIDPrimaryModel


class PartyType(models.TextChoices):
    ORGANIZATION = "organization", _("Təşkilat")
    PERSON = "person", _("Fiziki şəxs")


class PartyStatus(models.TextChoices):
    PROSPECT = "prospect", _("Prospect")
    ACTIVE = "active", _("Aktiv")
    INACTIVE = "inactive", _("Qeyri-aktiv")
    BLOCKED = "blocked", _("Bloklanıb")


class PartyRoleCode(models.TextChoices):
    RESIDENT = "resident", _("Rezident")
    PROSPECT = "prospect", _("Prospect")
    SUPPLIER = "supplier", _("Təchizatçı")
    CONTRACTOR = "contractor", _("Podratçı")
    PARTNER = "partner", _("Partnyor")
    OTHER = "other", _("Digər")


class PersonKind(models.TextChoices):
    RESIDENT_EMPLOYEE = "resident_employee", _("Rezident əməkdaş")
    CONTACT = "contact", _("Əlaqə şəxsi")
    VISITOR = "visitor", _("Qonaq")
    CONTRACTOR_EMPLOYEE = "contractor_employee", _("Podratçı əməkdaş")
    STAFF = "staff", _("City Point əməkdaş")


class Party(UUIDPrimaryModel):
    party_type = models.CharField(max_length=16, choices=PartyType.choices, default=PartyType.ORGANIZATION)
    legal_name = models.CharField(max_length=200)
    brand_name = models.CharField(max_length=200, blank=True)
    tax_id = models.CharField(max_length=64, blank=True, verbose_name=_("VÖEN"))
    status = models.CharField(max_length=16, choices=PartyStatus.choices, default=PartyStatus.ACTIVE)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=64, blank=True)
    legacy_resident_company = models.OneToOneField(
        "residents.ResidentCompany",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="party",
    )
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _("Party")
        verbose_name_plural = _("Parties")
        ordering = ["legal_name"]

    def __str__(self):
        return self.brand_name or self.legal_name

    @property
    def display_name(self):
        return self.brand_name or self.legal_name


class PartyRole(models.Model):
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="roles")
    role = models.CharField(max_length=32, choices=PartyRoleCode.choices)
    is_primary = models.BooleanField(default=False)

    class Meta:
        unique_together = ("party", "role")

    def __str__(self):
        return f"{self.party_id}:{self.role}"


class Person(UUIDPrimaryModel):
    full_name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=64, blank=True)
    party = models.ForeignKey(
        Party,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="people",
    )
    person_kind = models.CharField(max_length=32, choices=PersonKind.choices, default=PersonKind.CONTACT)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="person_profile",
    )
    legacy_employee = models.OneToOneField(
        "residents.ResidentEmployee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="person",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name
