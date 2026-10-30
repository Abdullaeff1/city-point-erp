import calendar
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.property.storage import private_plan_storage


class Occupancy(models.TextChoices):
    ACTIVE_LEASE = "active_lease", _("Aktiv icarə dövrü")
    VACANT = "vacant", _("Boş")
    MAINTENANCE = "maintenance", _("Texniki xidmət")


class CommercialStatus(models.TextChoices):
    VACANT = "vacant", _("Boş")
    RESERVED = "reserved", _("Rezerv")
    CONTRACTED = "contracted", _("Müqaviləli")
    ACTIVE = "active", _("Aktiv")
    NOTICE = "notice", _("Xəbərdarlıq")


class OperationalStatus(models.TextChoices):
    AVAILABLE = "available", _("Hazır")
    MAINTENANCE = "maintenance", _("Texniki xidmət")
    BLOCKED = "blocked", _("Dayandırılıb")


class ParkingAssignmentType(models.TextChoices):
    RESIDENT = "resident", _("Resident")
    EMPLOYEE = "employee", _("Employee")
    VISITOR = "visitor", _("Visitor")
    TEMPORARY = "temporary", _("Temporary")


class UtilityType(models.TextChoices):
    ELECTRIC = "electric", _("Electric")
    WATER = "water", _("Water")
    GAS = "gas", _("Gas")
    OTHER = "other", _("Other")


class Building(models.Model):
    name = models.CharField(max_length=120, default="City Point Business Center")
    code = models.CharField(max_length=32, unique=True, default="CP")

    def __str__(self):
        return self.name


class Floor(models.Model):
    building = models.ForeignKey(
        Building, on_delete=models.CASCADE, related_name="floors", verbose_name=_("Bina")
    )
    code = models.CharField(max_length=16, verbose_name=_("Kod"))
    name = models.CharField(max_length=64, verbose_name=_("Ad"))

    class Meta:
        unique_together = ("building", "code")
        verbose_name = _("Mərtəbə")
        verbose_name_plural = _("Mərtəbələr")

    def __str__(self):
        return f"{self.code} · {self.name}" if self.name else self.code


class Space(models.Model):
    code = models.CharField(max_length=64, unique=True, verbose_name=_("Kod"))
    name = models.CharField(max_length=120, blank=True, verbose_name=_("Ad"))
    floor = models.ForeignKey(
        Floor, on_delete=models.CASCADE, related_name="spaces", verbose_name=_("Mərtəbə")
    )
    resident = models.ForeignKey(
        "residents.ResidentCompany",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="spaces",
        verbose_name=_("Rezident"),
    )
    area_m2 = models.DecimalField(
        max_digits=10, decimal_places=1, default=0, verbose_name=_("Sahə (m²)")
    )
    access_zone = models.CharField(max_length=32, blank=True, verbose_name=_("Keçid zonası"))
    occupancy = models.CharField(
        max_length=32,
        choices=Occupancy.choices,
        default=Occupancy.ACTIVE_LEASE,
        verbose_name=_("Doluluq"),
    )
    cost_center = models.CharField(max_length=64, blank=True, verbose_name=_("Xərc mərkəzi"))
    plan_revision = models.CharField(max_length=32, blank=True, verbose_name=_("Plan versiyası"))
    commercial_status = models.CharField(
        max_length=24,
        choices=CommercialStatus.choices,
        default=CommercialStatus.VACANT,
        verbose_name=_("Kommersiya statusu"),
    )
    operational_status = models.CharField(
        max_length=24,
        choices=OperationalStatus.choices,
        default=OperationalStatus.AVAILABLE,
        verbose_name=_("Əməliyyat statusu"),
    )
    rentable_area_m2 = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("İcarəyə verilən sahə (m²)"),
    )
    base_rent_rate = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("AZN / m² / ay (istinad)"),
        verbose_name=_("Baza icarə tarifi"),
    )
    service_charge_rate = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("AZN / m² / ay (istinad)"),
        verbose_name=_("Xidmət haqqı tarifi"),
    )
    availability_date = models.DateField(
        null=True, blank=True, verbose_name=_("Əlçatanlıq tarixi")
    )
    fit_out_status = models.CharField(
        max_length=64, blank=True, verbose_name=_("Təmir / təchizat statusu")
    )
    is_public = models.BooleanField(default=False, verbose_name=_("İctimai"))
    public_description = models.TextField(blank=True, verbose_name=_("İctimai təsvir"))

    def __str__(self):
        return self.area_code

    @property
    def short_label(self):
        return self.area_code

    @property
    def area_code(self):
        """Company-facing space label: CP/F10/232."""
        raw = (self.floor.code or "").upper()
        if raw.startswith("F"):
            raw = raw[1:]
        try:
            floor_no = str(int(raw))
        except (TypeError, ValueError):
            floor_no = raw or "?"
        area = Decimal(str(self.area_m2 or "0"))
        if area == area.to_integral_value():
            area_text = str(int(area))
        else:
            area_text = format(area.normalize(), "f")
        return f"CP/F{floor_no}/{area_text}"


class Asset(models.Model):
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name="assets")
    name = models.CharField(max_length=160)
    asset_code = models.CharField(max_length=64, blank=True)

    def __str__(self):
        return self.name


class BuildingAssetCategory(models.TextChoices):
    HVAC = "hvac", _("HVAC")
    LIFT = "lift", _("Lift")
    ELECTRIC = "electric", _("Elektrik")
    FIRE = "fire", _("Yanğın")
    PUMP = "pump", _("Nasos")
    FURNITURE = "furniture", _("Mebel")
    OTHER = "other", _("Digər")


class BuildingAssetKind(models.TextChoices):
    EQUIPMENT = "equipment", _("Avadanlıq")
    INVENTORY = "inventory", _("İnventar")


EQUIPMENT_CATEGORIES = (
    BuildingAssetCategory.HVAC,
    BuildingAssetCategory.LIFT,
    BuildingAssetCategory.ELECTRIC,
    BuildingAssetCategory.FIRE,
    BuildingAssetCategory.PUMP,
    BuildingAssetCategory.OTHER,
)

INVENTORY_CATEGORIES = (
    BuildingAssetCategory.FURNITURE,
    BuildingAssetCategory.OTHER,
)


def categories_for_kind(kind: str):
    if kind == BuildingAssetKind.INVENTORY:
        return [(v, l) for v, l in BuildingAssetCategory.choices if v in INVENTORY_CATEGORIES]
    return [(v, l) for v, l in BuildingAssetCategory.choices if v in EQUIPMENT_CATEGORIES]


def add_one_month(value: date) -> date:
    month = value.month + 1
    year = value.year
    if month > 12:
        month = 1
        year += 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


class BuildingAsset(models.Model):
    """City Point equipment and goods kept in the building, inspected monthly."""

    name = models.CharField(max_length=160)
    code = models.CharField(max_length=64, blank=True)
    kind = models.CharField(
        max_length=16,
        choices=BuildingAssetKind.choices,
        default=BuildingAssetKind.EQUIPMENT,
        db_index=True,
    )
    category = models.CharField(
        max_length=24,
        choices=BuildingAssetCategory.choices,
        default=BuildingAssetCategory.OTHER,
    )
    floor = models.ForeignKey(
        Floor,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="building_assets",
    )
    location = models.CharField(max_length=160, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    last_inspected_on = models.DateField(null=True, blank=True)
    next_inspection_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["kind", "category", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.last_inspected_on and not self.next_inspection_on:
            self.next_inspection_on = add_one_month(self.last_inspected_on)
        super().save(*args, **kwargs)

    @property
    def inspection_due(self) -> bool:
        if not self.next_inspection_on:
            return False
        return self.next_inspection_on <= timezone.localdate()


class Contractor(models.Model):
    name = models.CharField(max_length=160)
    contact_email = models.EmailField(blank=True)
    phone = models.CharField(max_length=64, blank=True)
    party = models.ForeignKey(
        "parties.Party",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contractors",
    )

    def __str__(self):
        return self.name


class ParkingZone(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    building = models.ForeignKey(
        Building,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="parking_zones",
    )

    def __str__(self):
        return self.code


class ParkingSpot(models.Model):
    zone = models.ForeignKey(ParkingZone, on_delete=models.CASCADE, related_name="spots")
    code = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("zone", "code")

    def __str__(self):
        return f"{self.zone.code}:{self.code}"


class ParkingAssignment(models.Model):
    spot = models.ForeignKey(ParkingSpot, on_delete=models.CASCADE, related_name="assignments")
    party = models.ForeignKey(
        "parties.Party",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="parking_assignments",
    )
    vehicle_plate = models.CharField(max_length=32, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    assignment_type = models.CharField(
        max_length=24,
        choices=ParkingAssignmentType.choices,
        default=ParkingAssignmentType.RESIDENT,
    )

    def __str__(self):
        return f"{self.spot}:{self.vehicle_plate or self.party_id}"


class UtilityMeter(models.Model):
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name="meters")
    meter_code = models.CharField(max_length=64)
    utility_type = models.CharField(
        max_length=16,
        choices=UtilityType.choices,
        default=UtilityType.ELECTRIC,
    )
    unit = models.CharField(max_length=16, default="kWh")

    class Meta:
        unique_together = ("space", "meter_code")

    def __str__(self):
        return self.meter_code


class MeterReading(models.Model):
    meter = models.ForeignKey(UtilityMeter, on_delete=models.CASCADE, related_name="readings")
    reading = models.DecimalField(max_digits=14, decimal_places=3)
    read_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-read_at"]

    def __str__(self):
        return f"{self.meter_id}:{self.reading}"


class SpaceDrawingKind(models.TextChoices):
    DXF = "dxf", _("DXF / DWG")
    TECHNICAL_PLAN = "technical_plan", _("Texniki plan")


class SpaceDrawingAccessStatus(models.TextChoices):
    PENDING = "pending", _("Gözləyir")
    APPROVED = "approved", _("Təsdiqləndi")
    DENIED = "denied", _("İmtina")


def space_drawing_upload_to(instance, filename):
    return f"space_drawings/{instance.space_id}/{instance.kind}/{filename}"


def space_drawing_svg_upload_to(instance, filename):
    return f"space_drawings/{instance.space_id}/{instance.kind}/svg/{filename}"


class SpaceDrawing(models.Model):
    """Per-office DXF or technical plan (PDF/PNG) — private storage only."""

    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name="drawings")
    kind = models.CharField(max_length=32, choices=SpaceDrawingKind.choices)
    file = models.FileField(upload_to=space_drawing_upload_to, storage=private_plan_storage)
    svg_file = models.FileField(
        upload_to=space_drawing_svg_upload_to,
        storage=private_plan_storage,
        blank=True,
        null=True,
    )
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128, blank=True)
    package_id = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text=_("Import paket ID (məs. F08_Ofis_01)"),
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_space_drawings",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Sahə rəsmi")
        verbose_name_plural = _("Sahə rəsmləri")

    def __str__(self):
        return f"{self.space_id}:{self.kind}:{self.original_name}"

    def clean(self):
        name = (self.original_name or "").lower()
        if self.kind == SpaceDrawingKind.DXF and not name.endswith(".dxf"):
            raise ValidationError({"file": _("DWG tabı üçün yalnız .dxf faylı.")})
        if self.kind == SpaceDrawingKind.TECHNICAL_PLAN and not (
            name.endswith(".pdf") or name.endswith(".png")
        ):
            raise ValidationError({"file": _("Texniki plan üçün yalnız .pdf və ya .png.")})

    @property
    def is_png(self) -> bool:
        return (self.original_name or "").lower().endswith(".png")

    @property
    def is_pdf(self) -> bool:
        return (self.original_name or "").lower().endswith(".pdf")

    @property
    def has_svg_preview(self) -> bool:
        return bool(self.svg_file)


class SpaceDrawingAccessRequest(models.Model):
    """Resident request to download a space drawing; staff approves with TTL."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="space_drawing_access_requests",
    )
    drawing = models.ForeignKey(
        SpaceDrawing,
        on_delete=models.CASCADE,
        related_name="access_requests",
    )
    status = models.CharField(
        max_length=16,
        choices=SpaceDrawingAccessStatus.choices,
        default=SpaceDrawingAccessStatus.PENDING,
        db_index=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="decided_space_drawing_access_requests",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Sahə rəsm icazə sorğusu")
        verbose_name_plural = _("Sahə rəsm icazə sorğuları")

    def __str__(self):
        return f"{self.user_id}:{self.drawing_id}:{self.status}"

    @property
    def is_download_allowed(self) -> bool:
        if self.status != SpaceDrawingAccessStatus.APPROVED:
            return False
        if self.expires_at is None:
            return False
        return timezone.now() < self.expires_at

