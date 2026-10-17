"""Security floor plans, CAD revisions, devices, and pins."""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.security.storage import private_plan_storage


class PlanCategory(models.TextChoices):
    CAMERAS = "cameras", _("Kameralar")
    SIGNALING = "signaling", _("Siqnalizasiya")
    MIXED = "mixed", _("Qarışıq")


class ConversionStatus(models.TextChoices):
    PENDING = "pending", _("Gözləyir")
    PROCESSING = "processing", _("Emal olunur")
    READY = "ready", _("Hazır")
    FAILED = "failed", _("Uğursuz")
    UNSUPPORTED = "unsupported", _("Dəstəklənmir")


class SourceFormat(models.TextChoices):
    DWG = "dwg", "DWG"
    DXF = "dxf", "DXF"


class DeviceType(models.TextChoices):
    CAMERA = "camera", _("Kamera")
    ALARM_PANEL = "alarm_panel", _("Siqnal paneli")
    SENSOR = "sensor", _("Sensor")
    OTHER = "other", _("Digər")


class SecurityFloorPlan(models.Model):
    title = models.CharField(max_length=200)
    floor = models.ForeignKey(
        "property.Floor",
        on_delete=models.PROTECT,
        related_name="security_floor_plans",
    )
    category = models.CharField(
        max_length=16, choices=PlanCategory.choices, default=PlanCategory.MIXED
    )
    is_active = models.BooleanField(default=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_security_plans",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["floor__building__name", "floor__code", "title"]

    def __str__(self):
        return f"{self.title} ({self.floor})"

    @property
    def building(self):
        return self.floor.building

    def active_revision(self):
        return self.revisions.filter(is_active=True).first()


class SecurityFloorPlanRevision(models.Model):
    plan = models.ForeignKey(
        SecurityFloorPlan, on_delete=models.CASCADE, related_name="revisions"
    )
    revision_number = models.PositiveIntegerField()
    source_file = models.FileField(
        upload_to="security_plans/source/%Y/%m/",
        storage=private_plan_storage,
        max_length=500,
    )
    source_format = models.CharField(max_length=8, choices=SourceFormat.choices)
    svg_file = models.FileField(
        upload_to="security_plans/svg/%Y/%m/",
        storage=private_plan_storage,
        max_length=500,
        blank=True,
    )
    conversion_status = models.CharField(
        max_length=16,
        choices=ConversionStatus.choices,
        default=ConversionStatus.PENDING,
        db_index=True,
    )
    conversion_error = models.CharField(max_length=500, blank=True)
    conversion_tool = models.CharField(max_length=64, blank=True)
    conversion_version = models.CharField(max_length=64, blank=True)
    checksum = models.CharField(max_length=64, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_security_plan_revisions",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    converted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_security_plan_revisions",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-revision_number"]
        unique_together = [("plan", "revision_number")]
        constraints = [
            models.UniqueConstraint(
                fields=["plan"],
                condition=Q(is_active=True),
                name="uniq_active_revision_per_security_plan",
            )
        ]

    def __str__(self):
        return f"{self.plan_id} r{self.revision_number} ({self.conversion_status})"


class SecurityDevice(models.Model):
    name = models.CharField(max_length=160)
    device_type = models.CharField(
        max_length=16, choices=DeviceType.choices, default=DeviceType.CAMERA
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    location_note = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_security_devices",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


def _pct_validators():
    return [MinValueValidator(0), MaxValueValidator(100)]


class SecurityDevicePin(models.Model):
    revision = models.ForeignKey(
        SecurityFloorPlanRevision, on_delete=models.CASCADE, related_name="pins"
    )
    device = models.ForeignKey(
        SecurityDevice, on_delete=models.CASCADE, related_name="pins"
    )
    x_pct = models.DecimalField(
        max_digits=6, decimal_places=2, validators=_pct_validators()
    )
    y_pct = models.DecimalField(
        max_digits=6, decimal_places=2, validators=_pct_validators()
    )
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_security_pins",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_security_pins",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        unique_together = [("revision", "device")]

    def __str__(self):
        return f"{self.device} @ {self.x_pct},{self.y_pct}"

    def clean(self):
        super().clean()
        if self.revision_id and self.device_id:
            cat = self.revision.plan.category
            dtype = self.device.device_type
            if cat == PlanCategory.CAMERAS and dtype != DeviceType.CAMERA:
                raise ValidationError(_("Bu cihaz tipi plan kateqoriyasına uyğun deyil."))
            if cat == PlanCategory.SIGNALING and dtype not in {
                DeviceType.ALARM_PANEL,
                DeviceType.SENSOR,
            }:
                raise ValidationError(_("Bu cihaz tipi plan kateqoriyasına uyğun deyil."))
