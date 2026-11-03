from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


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
        help_text="Operator-only şirkət — rezident siyahısına düşmür",
    )
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="archived_resident_companies",
    )

    # Legal / registration
    voen = models.CharField(max_length=32, blank=True, verbose_name=_("VÖEN"))
    legal_form = models.CharField(
        max_length=64, blank=True, verbose_name=_("Hüquqi forma")
    )
    charter_capital = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Nizamnamə kapitalı (AZN)"),
    )
    justice_registration_no = models.CharField(
        max_length=64, blank=True, verbose_name=_("Ədliyyə qeydiyyat №")
    )
    justice_registration_date = models.DateField(
        null=True, blank=True, verbose_name=_("Ədliyyə qeydiyyat tarixi")
    )
    registry_extract_ref = models.CharField(
        max_length=128,
        blank=True,
        verbose_name=_("Reyestrdən çıxarış"),
        help_text=_("Reyestr çıxarışı nömrəsi / istinad (sənəd tipi: Reyestrdən çıxarış)"),
    )
    legal_address = models.CharField(max_length=255, blank=True, verbose_name=_("Hüquqi ünvan"))
    actual_address = models.CharField(max_length=255, blank=True, verbose_name=_("Faktiki ünvan"))

    # Contacts
    contact_email = models.EmailField(blank=True, verbose_name=_("Əsas email"))
    billing_email = models.EmailField(blank=True, verbose_name=_("Faktura email"))
    phone = models.CharField(max_length=64, blank=True, verbose_name=_("Telefon"))
    website = models.URLField(blank=True, verbose_name=_("Veb-sayt"))
    manager_name = models.CharField(max_length=160, blank=True, verbose_name=_("Direktor / rəhbər"))
    manager_position = models.CharField(max_length=120, blank=True, verbose_name=_("Rəhbər vəzifəsi"))
    manager_phone = models.CharField(max_length=64, blank=True, verbose_name=_("Rəhbər telefon"))
    manager_email = models.EmailField(blank=True, verbose_name=_("Rəhbər email"))
    contact_person_name = models.CharField(max_length=160, blank=True, verbose_name=_("Əlaqəli şəxs"))
    contact_person_phone = models.CharField(max_length=64, blank=True, verbose_name=_("Əlaqə telefon"))
    contact_person_email = models.EmailField(blank=True, verbose_name=_("Əlaqə email"))

    # Bank (single primary account)
    bank_name = models.CharField(max_length=160, blank=True, verbose_name=_("Bank adı"))
    bank_voen = models.CharField(max_length=32, blank=True, verbose_name=_("Bank VÖEN"))
    bank_code = models.CharField(max_length=32, blank=True, verbose_name=_("Bank kodu"))
    swift_bic = models.CharField(max_length=32, blank=True, verbose_name=_("SWIFT/BIC"))
    iban = models.CharField(max_length=64, blank=True, verbose_name=_("IBAN"))
    account_number = models.CharField(max_length=64, blank=True, verbose_name=_("Hesab nömrəsi"))
    correspondent_account = models.CharField(
        max_length=64, blank=True, verbose_name=_("Müxbir hesab")
    )
    bank_branch = models.CharField(max_length=160, blank=True, verbose_name=_("Bank filialı"))
    bank_currency = models.CharField(
        max_length=8, blank=True, default="AZN", verbose_name=_("Hesab valyutası")
    )

    contract_start = models.DateField(null=True, blank=True)
    contract_end = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_resident_companies",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_resident_companies",
    )

    class Meta:
        verbose_name = _("Rezident şirkət")
        verbose_name_plural = _("Rezident şirkətlər")

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name) or f"company-{timezone.now().timestamp():.0f}"
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        voen = (self.voen or "").strip()
        if voen and (not voen.isdigit() or len(voen) != 10):
            raise ValidationError({"voen": _("VÖEN 10 rəqəmdən ibarət olmalıdır.")})
        bank_voen = (self.bank_voen or "").strip()
        if bank_voen and (not bank_voen.isdigit() or len(bank_voen) != 10):
            raise ValidationError({"bank_voen": _("Bank VÖEN 10 rəqəmdən ibarət olmalıdır.")})
        if self.charter_capital is not None and self.charter_capital < Decimal("0"):
            raise ValidationError({"charter_capital": _("Nizamnamə kapitalı mənfi ola bilməz.")})
        if self.contract_start and self.contract_end and self.contract_start > self.contract_end:
            raise ValidationError({"contract_end": _("Bitmə tarixi başlanğıcdan əvvəl ola bilməz.")})
        if self.is_archived and self.portal_active:
            raise ValidationError(
                {"portal_active": _("Arxivdə olan şirkətin portalı aktiv ola bilməz.")}
            )

    @property
    def display_address(self) -> str:
        return (self.actual_address or "").strip() or (self.legal_address or "").strip()

    def __str__(self):
        return self.name


class AccessLevel(models.TextChoices):
    LEVEL_1 = "1", "Səviyyə 1 — turn_back yox"
    LEVEL_2 = "2", "Səviyyə 2 — turn_back icazəli"


class CardOrderStatus(models.TextChoices):
    NONE = "none", "—"
    SUBMITTED = "submitted", "Göndərilib"
    UNDER_REVIEW = "under_review", "Yoxlanılır"
    APPROVED = "approved", "Təsdiqlənib"
    PREPARED = "prepared", "Hazırlanır"
    ISSUED = "issued", "Verilib"
    REJECTED = "rejected", "Rədd"
    CANCELLED = "cancelled", "Ləğv"


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
    card_order_status = models.CharField(
        max_length=16,
        choices=CardOrderStatus.choices,
        default=CardOrderStatus.NONE,
        blank=True,
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


class AccessResult(models.TextChoices):
    GRANTED = "granted", "Uğurlu"
    DENIED = "denied", "Uğursuz"


class AccessEvent(models.Model):
    """Immutable attendance punch — retained indefinitely (AxTrax delete-proof archive).

    Snapshots keep name/card readable even if the employee record is later renamed.
    Employee FK is PROTECT so history cannot be wiped by a casual delete.
    """

    employee = models.ForeignKey(
        ResidentEmployee,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="access_events",
    )
    event_type = models.CharField(max_length=8, choices=AccessEventType.choices)
    result = models.CharField(
        max_length=16,
        choices=AccessResult.choices,
        default=AccessResult.GRANTED,
        db_index=True,
    )
    occurred_at = models.DateTimeField()
    # Denormalized archive fields (filled at sync time — punch anındakı vəziyyət)
    employee_name = models.CharField(max_length=160, blank=True)
    card_number = models.CharField(max_length=32, blank=True, db_index=True)
    company_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Punch anında şirkət id (snapshot)",
    )
    company_name = models.CharField(
        max_length=160,
        blank=True,
        help_text="Punch anında şirkət adı (snapshot)",
    )
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
