from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class CompanyStatus(models.TextChoices):
    ACTIVE = "active", "Aktiv"
    INACTIVE = "inactive", "Qeyri-aktiv"


class ResidentCompany(models.Model):
    name = models.CharField(max_length=160)
    slug = models.SlugField(unique=True)
    status = models.CharField(max_length=16, choices=CompanyStatus.choices, default=CompanyStatus.ACTIVE)
    portal_active = models.BooleanField(default=True)
    is_internal = models.BooleanField(
        default=False,
        help_text="Operator / City Point özü — rezident siyahısına düşmür",
    )
    contact_email = models.EmailField(blank=True)
    contract_start = models.DateField(null=True, blank=True)
    contract_end = models.DateField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class AccessLevel(models.TextChoices):
    LEVEL_1 = "1", "Səviyyə 1 — turn_back yox"
    LEVEL_2 = "2", "Səviyyə 2 — turn_back icazəli"


class ResidentEmployee(models.Model):
    """Employee master — never hard-delete if AccessEvent exists (PROTECT).

    AxTrax-dan silinəndə soft-deactivate olur; giriş/çıxış tarixçəsi qalır.
    """

    company = models.ForeignKey(ResidentCompany, on_delete=models.CASCADE, related_name="employees")
    full_name = models.CharField(max_length=160)
    card_number = models.CharField(max_length=32, blank=True)
    access_level = models.CharField(
        max_length=8,
        choices=AccessLevel.choices,
        default=AccessLevel.LEVEL_1,
        help_text="AxTraxNG access group: 1 = turn_back yox; 2 = turn_back icazəli",
    )
    id_document = models.FileField(
        upload_to="employees/id/%Y/%m/",
        blank=True,
        help_text="Şəxsiyyət vəsiqəsi nüsxəsi (kart sifarişi üçün)",
    )
    is_active = models.BooleanField(default=True)
    deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="İşdən çıxış / AxTrax-dan silinmə vaxtı — tarixçəyə qədər baxış üçün",
    )

    class Meta:
        indexes = [
            models.Index(fields=["company", "is_active", "full_name"]),
        ]

    def mark_inactive(self, *, when=None):
        when = when or timezone.now()
        if self.is_active or self.deactivated_at is None:
            self.is_active = False
            if self.deactivated_at is None:
                self.deactivated_at = when
            self.save(update_fields=["is_active", "deactivated_at"])

    def mark_active(self):
        self.is_active = True
        self.deactivated_at = None
        self.save(update_fields=["is_active", "deactivated_at"])

    def __str__(self):
        return self.full_name


class AccessEventType(models.TextChoices):
    IN = "in", "Giriş"
    OUT = "out", "Çıxış"


class AccessEvent(models.Model):
    """Immutable attendance punch — retained indefinitely (AxTrax delete-proof archive).

    Snapshots keep name/card readable even if the employee record is later renamed.
    Employee FK is PROTECT so history cannot be wiped by a casual delete.
    """

    employee = models.ForeignKey(
        ResidentEmployee,
        on_delete=models.PROTECT,
        related_name="access_events",
    )
    event_type = models.CharField(max_length=8, choices=AccessEventType.choices)
    occurred_at = models.DateTimeField()
    # Denormalized archive fields (filled at sync time)
    employee_name = models.CharField(max_length=160, blank=True)
    card_number = models.CharField(max_length=32, blank=True)
    axtrax_employee_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    reader_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    reader_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="AxTrax tblReader.tDescReader (tam ad)",
    )

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["employee", "occurred_at"]),
            models.Index(fields=["occurred_at"]),
        ]

    def __str__(self):
        label = self.employee_name or (self.employee.full_name if self.employee_id else "?")
        return f"{label} {self.event_type} @ {self.occurred_at}"


class RapidCardSwipeAlert(models.Model):
    """Security alert: same employee tapped card 3+ times within a short window."""

    employee = models.ForeignKey(
        ResidentEmployee,
        on_delete=models.PROTECT,
        related_name="rapid_swipe_alerts",
    )
    employee_name = models.CharField(max_length=160)
    card_number = models.CharField(max_length=32, blank=True)
    company_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    company_name = models.CharField(max_length=160, blank=True)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    swipe_count = models.PositiveIntegerField()
    swipes = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="acknowledged_rapid_swipe_alerts",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["employee", "window_start"]),
            models.Index(fields=["acknowledged_at", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "window_start"],
                name="uniq_rapid_swipe_employee_window_start",
            ),
        ]

    def __str__(self):
        return f"{self.employee_name} ×{self.swipe_count} @ {self.window_start}"

    @property
    def is_open(self):
        return self.acknowledged_at is None


class ShaftAccessAlert(models.Model):
    """Security alert: card used on a Shaft* reader (lift/shaft door)."""

    employee = models.ForeignKey(
        ResidentEmployee,
        on_delete=models.PROTECT,
        related_name="shaft_access_alerts",
    )
    access_event = models.OneToOneField(
        AccessEvent,
        on_delete=models.PROTECT,
        related_name="shaft_alert",
    )
    employee_name = models.CharField(max_length=160)
    card_number = models.CharField(max_length=32, blank=True)
    company_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    company_name = models.CharField(max_length=160, blank=True)
    occurred_at = models.DateTimeField(db_index=True)
    event_type = models.CharField(max_length=8, choices=AccessEventType.choices)
    reader_id = models.PositiveIntegerField(null=True, blank=True)
    reader_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="AxTrax oxuyucu adı (tam)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="acknowledged_shaft_access_alerts",
    )

    class Meta:
        ordering = ["-occurred_at", "-created_at"]
        indexes = [
            models.Index(fields=["acknowledged_at", "occurred_at"]),
        ]

    def __str__(self):
        return f"{self.employee_name} @ {self.reader_name or 'Shaft'} {self.occurred_at}"

    @property
    def is_open(self):
        return self.acknowledged_at is None
