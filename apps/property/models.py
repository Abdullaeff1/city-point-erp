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
    is_public = models.BooleanField(default=False)
    public_description = models.TextField(blank=True)

    def __str__(self):
        return self.code

    @property
    def short_label(self):
        return self.name or self.code.split("-")[-1]


class Asset(models.Model):
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name="assets")
    name = models.CharField(max_length=160)
    asset_code = models.CharField(max_length=64, blank=True)

    def __str__(self):
        return self.name


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
