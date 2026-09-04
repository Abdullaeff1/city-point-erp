from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    MANAGEMENT = "management", "Rəhbərlik"
    RECEPTION = "reception", "Reception"
    SERVICE_DESK = "service_desk", "Service Desk"
    PROPERTY_FM = "property_fm", "Property / FM"
    RESIDENT_USER = "resident_user", "Rezident"


STAFF_ROLES = {
    Role.ADMIN,
    Role.MANAGEMENT,
    Role.RECEPTION,
    Role.SERVICE_DESK,
    Role.PROPERTY_FM,
}


class User(AbstractUser):
    email = models.EmailField("E-poçt", unique=True)
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.RESIDENT_USER)
    resident_company = models.ForeignKey(
        "residents.ResidentCompany",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="portal_users",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        verbose_name = "İstifadəçi"
        verbose_name_plural = "İstifadəçilər"

    def is_staff_role(self):
        return self.role in STAFF_ROLES

    def can_access_erp(self):
        return self.is_staff_role()

    def can_access_portal(self):
        return self.role == Role.RESIDENT_USER or self.is_staff_role()
