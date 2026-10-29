import calendar
from datetime import date
from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Occupancy(models.TextChoices):
    ACTIVE_LEASE = "active_lease", "Aktiv icarə dövrü"
    VACANT = "vacant", "Boş"
    MAINTENANCE = "maintenance", "Texniki xidmət"


class CommercialStatus(models.TextChoices):
    VACANT = "vacant", _("Vacant")
    RESERVED = "reserved", _("Reserved")
    CONTRACTED = "contracted", _("Contracted")
    ACTIVE = "active", _("Active")
    NOTICE = "notice", _("Notice")


class OperationalStatus(models.TextChoices):
    AVAILABLE = "available", _("Available")
    MAINTENANCE = "maintenance", _("Maintenance")
    BLOCKED = "blocked", _("Blocked")


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
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name="floors")
    code = models.CharField(max_length=16)
    name = models.CharField(max_length=64)

    class Meta:
        unique_together = ("building", "code")

    def __str__(self):
        return self.code


class Space(models.Model):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120, blank=True)
    floor = models.ForeignKey(Floor, on_delete=models.CASCADE, related_name="spaces")
    resident = models.ForeignKey(
        "residents.ResidentCompany",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="spaces",
    )
    area_m2 = models.DecimalField(max_digits=10, decimal_places=1, default=0)
    access_zone = models.CharField(max_length=32, blank=True)
    occupancy = models.CharField(max_length=32, choices=Occupancy.choices, default=Occupancy.ACTIVE_LEASE)
    cost_center = models.CharField(max_length=64, blank=True)
    plan_revision = models.CharField(max_length=32, blank=True)
    commercial_status = models.CharField(
        max_length=24,
        choices=CommercialStatus.choices,
        default=CommercialStatus.VACANT,
    )
    operational_status = models.CharField(
        max_length=24,
        choices=OperationalStatus.choices,
        default=OperationalStatus.AVAILABLE,
    )
    rentable_area_m2 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    base_rent_rate = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, help_text="AZN / m² / ay (istinad)"
    )
    service_charge_rate = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, help_text="AZN / m² / ay (istinad)"
    )
    availability_date = models.DateField(null=True, blank=True)
    fit_out_status = models.CharField(max_length=64, blank=True)
    is_public = models.BooleanField(default=False)
    public_description = models.TextField(blank=True)

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
