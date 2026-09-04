from django.db import models


class Occupancy(models.TextChoices):
    ACTIVE_LEASE = "active_lease", "Aktiv icarə dövrü"
    VACANT = "vacant", "Boş"
    MAINTENANCE = "maintenance", "Texniki xidmət"


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

    def __str__(self):
        return self.name
