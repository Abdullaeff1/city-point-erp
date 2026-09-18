from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class CompanyStatus(models.TextChoices):
    ACTIVE = "active", "Aktiv"
    INACTIVE = "inactive", "Qeyri-aktiv"


class ResidentCompany(models.Model):
    name = models.CharField(max_length=160)
    slug = models.SlugField(unique=True)
    status = models.CharField(max_length=16, choices=CompanyStatus.choices, default=CompanyStatus.ACTIVE)
    portal_active = models.BooleanField(default=True)
    is_internal = models.BooleanField(
        default=False,
        help_text="Operator / City Point özü — rezident siyahısına düşmür",
    )
    contact_email = models.EmailField(blank=True)
    contract_start = models.DateField(null=True, blank=True)
    contract_end = models.DateField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ResidentEmployee(models.Model):
    """Employee master — never hard-delete if AccessEvent exists (PROTECT).

    AxTrax-dan silinəndə soft-deactivate olur; giriş/çıxış tarixçəsi qalır.
    """

    company = models.ForeignKey(ResidentCompany, on_delete=models.CASCADE, related_name="employees")
    full_name = models.CharField(max_length=160)
    card_number = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)
    deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="İşdən çıxış / AxTrax-dan silinmə vaxtı — tarixçəyə qədər baxış üçün",
    )

    class Meta:
        indexes = [
            models.Index(fields=["company", "is_active", "full_name"]),
        ]

    def mark_inactive(self, *, when=None):
        when = when or timezone.now()
        if self.is_active or self.deactivated_at is None:
            self.is_active = False
            if self.deactivated_at is None:
                self.deactivated_at = when
            self.save(update_fields=["is_active", "deactivated_at"])

    def mark_active(self):
        self.is_active = True
        self.deactivated_at = None
        self.save(update_fields=["is_active", "deactivated_at"])

    def __str__(self):
        return self.full_name


class AccessEventType(models.TextChoices):
    IN = "in", "Giriş"
    OUT = "out", "Çıxış"


class AccessEvent(models.Model):
    """Immutable attendance punch — retained indefinitely (AxTrax delete-proof archive).

    Snapshots keep name/card readable even if the employee record is later renamed.
    Employee FK is PROTECT so history cannot be wiped by a casual delete.
    """

    employee = models.ForeignKey(
        ResidentEmployee,
        on_delete=models.PROTECT,
        related_name="access_events",
    )
    event_type = models.CharField(max_length=8, choices=AccessEventType.choices)
    occurred_at = models.DateTimeField()
    # Denormalized archive fields (filled at sync time)
    employee_name = models.CharField(max_length=160, blank=True)
    card_number = models.CharField(max_length=32, blank=True)
    axtrax_employee_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["employee", "occurred_at"]),
            models.Index(fields=["occurred_at"]),
        ]

    def __str__(self):
        label = self.employee_name or (self.employee.full_name if self.employee_id else "?")
        return f"{label} {self.event_type} @ {self.occurred_at}"
