from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    ADMIN = "admin", _("Admin")
    MANAGEMENT = "management", _("Rəhbərlik")
    RECEPTION = "reception", _("Reception")
    SERVICE_DESK = "service_desk", _("Service Desk")
    PROPERTY_FM = "property_fm", _("Property / FM")
    RESIDENT_USER = "resident_user", _("Rezident")


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

    @property
    def initials(self):
        name = (self.get_full_name() or "").strip()
        if name:
            parts = [p for p in name.split() if p]
            if len(parts) >= 2:
                return (parts[0][0] + parts[1][0]).upper()
            return parts[0][:2].upper()
        return (self.email or "?")[:2].upper()

    @property
    def display_name(self):
        return self.get_full_name().strip() or self.email
