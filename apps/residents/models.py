from django.db import models
from django.utils.text import slugify


class CompanyStatus(models.TextChoices):
    ACTIVE = "active", "Aktiv"
    INACTIVE = "inactive", "Qeyri-aktiv"


class ResidentCompany(models.Model):
    name = models.CharField(max_length=160)
    slug = models.SlugField(unique=True)
    status = models.CharField(max_length=16, choices=CompanyStatus.choices, default=CompanyStatus.ACTIVE)
    portal_active = models.BooleanField(default=True)
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
    company = models.ForeignKey(ResidentCompany, on_delete=models.CASCADE, related_name="employees")
    full_name = models.CharField(max_length=160)
    card_number = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.full_name


class AccessEventType(models.TextChoices):
    IN = "in", "Giriş"
    OUT = "out", "Çıxış"


class AccessEvent(models.Model):
    employee = models.ForeignKey(ResidentEmployee, on_delete=models.CASCADE, related_name="access_events")
    event_type = models.CharField(max_length=8, choices=AccessEventType.choices)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["-occurred_at"]
