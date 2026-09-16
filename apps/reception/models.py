from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class VisitStatus(models.TextChoices):
    PRE_REGISTERED = "pre_registered", _("Əvvəlcədən qeyd")
    WAITING = "waiting", _("Gözləyir")
    INSIDE = "inside", _("İçəridə")
    LEFT = "left", _("Çıxış edib")
    CANCELLED = "cancelled", _("Ləğv")
    NO_SHOW = "no_show", _("Gəlməyib")
    RETURN_PENDING = "return_pending", _("Vəsiqə gözləyir")


class VisitorAccessStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    ACTIVE = "active", _("Active")
    EXPIRED = "expired", _("Expired")
    REVOKED = "revoked", _("Revoked")
    FAILED = "failed", _("Failed")


class SyncStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    SUCCESS = "success", _("Success")
    ERROR = "error", _("Error")


class VisitorType(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Guest(models.Model):
    first_name = models.CharField(max_length=80, blank=True)
    last_name = models.CharField(max_length=80, blank=True)
    # Kept for migration/compat; prefer first_name + last_name
    full_name = models.CharField(max_length=160, blank=True)
    fin_code = models.CharField(max_length=32, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name", "full_name"]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        parts = f"{self.first_name} {self.last_name}".strip()
        return parts or self.full_name or "—"

    def save(self, *args, **kwargs):
        if self.fin_code:
            self.fin_code = normalize_fin(self.fin_code)
        if not self.full_name and (self.first_name or self.last_name):
            self.full_name = f"{self.first_name} {self.last_name}".strip()
        if (self.first_name or self.last_name) is not None and self.full_name and not self.first_name:
            # leave as-is if only full_name set
            pass
        super().save(*args, **kwargs)


def normalize_fin(value: str) -> str:
    return "".join(ch for ch in (value or "").upper().strip() if ch.isalnum())


def mask_fin(value: str) -> str:
    fin = normalize_fin(value)
    if len(fin) < 5:
        return "****" if fin else "—"
    return f"{fin[:3]}****{fin[-2:]}"


class GuestVisit(models.Model):
    guest = models.ForeignKey(Guest, on_delete=models.CASCADE, related_name="visits")
    company = models.ForeignKey(
        "residents.ResidentCompany", on_delete=models.CASCADE, related_name="guest_visits"
    )
    host = models.ForeignKey(
        "residents.ResidentEmployee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hosted_visits",
    )
    visit_type = models.ForeignKey(
        VisitorType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="visits",
    )
    floor = models.ForeignKey("property.Floor", null=True, blank=True, on_delete=models.SET_NULL)
    space = models.ForeignKey("property.Space", null=True, blank=True, on_delete=models.SET_NULL)
    location_note = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=VisitStatus.choices, default=VisitStatus.WAITING)
    scheduled_for = models.DateField(default=timezone.localdate)
    check_in_at = models.DateTimeField(null=True, blank=True)
    check_out_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    pre_registered = models.BooleanField(default=False)
    invite_code = models.CharField(max_length=32, blank=True, db_index=True)
    expected_arrival = models.DateTimeField(null=True, blank=True)
    created_by_portal_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="portal_guest_visits",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_guest_visits",
    )
    id_document_held = models.BooleanField(default=False)
    id_document_returned_at = models.DateTimeField(null=True, blank=True)
    document_note = models.CharField(max_length=255, blank=True)
    id_override_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-check_in_at", "-created_at"]

    def __str__(self):
        return f"{self.guest} / {self.company}"

    @property
    def id_document_label(self):
        if self.id_document_returned_at:
            return _("Qaytarılıb")
        if self.id_document_held:
            return _("Alınıb")
        if self.status == VisitStatus.RETURN_PENDING:
            return _("Qaytarılmayıb")
        return _("—")


class VisitorAccess(models.Model):
    visit = models.OneToOneField(GuestVisit, on_delete=models.CASCADE, related_name="visitor_access")
    provider = models.CharField(max_length=64, default="mock")
    external_id = models.CharField(max_length=128, blank=True)
    credential = models.CharField(max_length=128, blank=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=VisitorAccessStatus.choices, default=VisitorAccessStatus.PENDING
    )
    sync_status = models.CharField(max_length=16, choices=SyncStatus.choices, default=SyncStatus.PENDING)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.visit_id}:{self.status}"
