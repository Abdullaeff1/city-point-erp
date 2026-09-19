from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    ADMIN = "admin", _("Admin")
    MANAGEMENT = "management", _("Rəhbərlik")
    RECEPTION = "reception", _("Reception")
    SERVICE_DESK = "service_desk", _("Service Desk")
    PROPERTY_FM = "property_fm", _("Property / FM")
    SECURITY = "security", _("Təhlükəsizlik")
    RESIDENT_USER = "resident_user", _("Rezident")


STAFF_ROLES = {
    Role.ADMIN,
    Role.MANAGEMENT,
    Role.RECEPTION,
    Role.SERVICE_DESK,
    Role.PROPERTY_FM,
    Role.SECURITY,
}

SECURITY_PORTAL_ROLES = {
    Role.SECURITY,
    Role.ADMIN,
    Role.MANAGEMENT,
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
    must_set_password = models.BooleanField(
        default=False,
        help_text=_("Invite / admin reset sonrası ilk şifrə təyini tələb olunsun"),
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        verbose_name = "İstifadəçi"
        verbose_name_plural = "İstifadəçilər"

    def is_staff_role(self):
        return self.role in STAFF_ROLES

    def can_access_erp(self):
        # Təhlükəsizlik öz portalından işləyir; tam ERP deyil
        return self.role in STAFF_ROLES and self.role != Role.SECURITY

    def can_access_security_portal(self):
        return self.role in SECURITY_PORTAL_ROLES

    def can_access_portal(self):
        if self.role == Role.SECURITY:
            return False
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


class PortalInvite(models.Model):
    """One-time invite / password-set token for portal (and optional staff) users.

    Raw token is emailed once; only sha256 hash is stored.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="portal_invites")
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sent_portal_invites",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"invite:{self.user_id}:{self.expires_at.date()}"

    @property
    def is_valid(self):
        if self.used_at is not None:
            return False
        return timezone.now() < self.expires_at
