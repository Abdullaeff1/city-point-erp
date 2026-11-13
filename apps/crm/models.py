from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class LeadSource(models.TextChoices):
    WEBSITE = "website", _("Website")
    PHONE = "phone", _("Phone")
    EMAIL = "email", _("Email")
    WALK_IN = "walk_in", _("Walk-in")
    REFERRAL = "referral", _("Referral")
    MANUAL = "manual", _("Manual")
    TARGETING = "targeting", _("Targeting")
    COLD_CALL = "cold_call", _("Cold call")
    EMAIL_MARKETING = "email_marketing", _("Email marketing")
    SOCIAL_MEDIA = "social_media", _("Social media")
    BILLBOARD = "billboard", _("Billboard")
    DIRECT = "direct", _("Direct")
    OTHER = "other", _("Other")


class LeadStatus(models.TextChoices):
    """Legacy status — prefer qualification / record_status / pipeline_stage."""

    NEW = "new", _("New")
    QUALIFIED = "qualified", _("Qualified")
    DISQUALIFIED = "disqualified", _("Disqualified")
    CONVERTED = "converted", _("Converted")


class Qualification(models.TextChoices):
    UNREVIEWED = "unreviewed", _("Qiymətləndirilməyib")
    POTENTIAL = "potential", _("Potensial")
    NON_POTENTIAL = "non_potential", _("Qeyri-potensial")


class RecordStatus(models.TextChoices):
    OPEN = "open", _("Açıq")
    WAITING = "waiting", _("Gözləntidə")
    CLOSED = "closed", _("Bağlı")


class PipelineStage(models.TextChoices):
    WORKING = "working", _("İşlənilir")
    CONTACT_PENDING = "contact_pending", _("Cavab gözlənilir")
    VIEWING_SCHEDULED = "viewing_scheduled", _("Sahəyə baxış planlaşdırılıb")
    VIEWING_COMPLETED = "viewing_completed", _("Sahəyə baxış keçirilib")
    MEETING_SCHEDULED = "meeting_scheduled", _("Görüş təyin olunub")
    NEGOTIATION = "negotiation", _("Danışıqlar")
    OFFER_SENT = "offer_sent", _("Təklif göndərilib")
    LEASE_STAGE = "lease_stage", _("Müqavilə mərhələsi")
    WON = "won", _("Qazanıldı")
    LOST = "lost", _("İtirildi")
    ON_HOLD = "on_hold", _("Gözləntidə")


class Outcome(models.TextChoices):
    COOPERATION_SECURED = "cooperation_secured", _("Əməkdaşlıq təmin olunub")
    OFFER_REJECTED = "offer_rejected", _("Təklif qəbul olunmayıb")
    NO_RESPONSE = "no_response", _("Geri dönüş yoxdur")
    NOT_INTERESTED = "not_interested", _("Maraqlı deyil")
    INVALID_REQUEST = "invalid_request", _("Yanlış sorğu")
    OTHER = "other", _("Digər")


class OpportunityStatus(models.TextChoices):
    OPEN = "open", _("Open")
    WON = "won", _("Won")
    LOST = "lost", _("Lost")


class OfferStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    PENDING_APPROVAL = "pending_approval", _("Təsdiq gözləyir")
    APPROVED = "approved", _("Təsdiqlənib")
    SENT = "sent", _("Sent")
    NEGOTIATION = "negotiation", _("Negotiation")
    ACCEPTED = "accepted", _("Accepted")
    REJECTED = "rejected", _("Rejected")


class ActivityType(models.TextChoices):
    CALL = "call", _("Zəng")
    EMAIL = "email", _("E-poçt")
    WHATSAPP = "whatsapp", _("WhatsApp")
    MEETING = "meeting", _("Görüş")
    VIEWING = "viewing", _("Sahəyə baxış")
    NOTE = "note", _("Qeyd")
    REMINDER = "reminder", _("Xatırlatma")
    STATUS_CHANGE = "status_change", _("Status dəyişikliyi")


class LeaseApplicationStatus(models.TextChoices):
    DRAFT = "draft", _("Qaralama")
    SUBMITTED_TO_ACCOUNTING = "submitted_to_accounting", _("Mühasibə göndərilib")
    UNDER_REVIEW = "under_review", _("Baxılır")
    RETURNED_FOR_CORRECTION = "returned_for_correction", _("Düzəlişə qaytarılıb")
    LEASE_DRAFT_CREATED = "lease_draft_created", _("İcarə qaralaması yaradılıb")
    SIGNED_DOCUMENTS_RECEIVED = "signed_documents_received", _("İmzalanmış sənədlər")
    COMPLETED = "completed", _("Tamamlanıb")
    CANCELLED = "cancelled", _("Ləğv")


class Lead(models.Model):
    full_name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=64, blank=True)
    company_name = models.CharField(max_length=200, blank=True)
    source = models.CharField(max_length=32, choices=LeadSource.choices, default=LeadSource.MANUAL)
    source_note = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=24, choices=LeadStatus.choices, default=LeadStatus.NEW)
    qualification = models.CharField(
        max_length=24, choices=Qualification.choices, default=Qualification.UNREVIEWED
    )
    qualification_reason = models.TextField(blank=True)
    record_status = models.CharField(
        max_length=16, choices=RecordStatus.choices, default=RecordStatus.OPEN
    )
    pipeline_stage = models.CharField(
        max_length=32, choices=PipelineStage.choices, default=PipelineStage.WORKING
    )
    outcome = models.CharField(max_length=32, choices=Outcome.choices, blank=True)
    outcome_note = models.TextField(blank=True)
    inquired_at = models.DateField(null=True, blank=True)
    min_area_m2 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    max_area_m2 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    employee_count = models.PositiveIntegerField(null=True, blank=True)
    employee_count_raw = models.CharField(max_length=64, blank=True)
    initial_note = models.TextField(blank=True)
    message = models.TextField(blank=True)
    contact_missing_reason = models.TextField(blank=True)
    interested_space = models.ForeignKey(
        "property.Space",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="leads",
    )
    party = models.ForeignKey(
        "parties.Party",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="leads",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_leads",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_leads",
    )
    external_id = models.CharField(max_length=128, blank=True, null=True, unique=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.company_name or self.full_name or f"Lead #{self.pk}"

    def clean(self):
        has_contact = any(
            [
                (self.company_name or "").strip(),
                (self.full_name or "").strip(),
                (self.phone or "").strip(),
                (self.email or "").strip(),
            ]
        )
        if not has_contact and not (self.contact_missing_reason or "").strip():
            raise ValidationError(
                _("Şirkət / əlaqə / telefon / e-poçtdan ən azı biri və ya səbəb tələb olunur.")
            )
        if self.qualification == Qualification.NON_POTENTIAL and not (self.qualification_reason or "").strip():
            raise ValidationError({"qualification_reason": _("Qeyri-potensial üçün səbəb məcburidir.")})
        if self.pipeline_stage in (PipelineStage.LOST, PipelineStage.WON) or self.record_status == RecordStatus.CLOSED:
            if self.pipeline_stage == PipelineStage.LOST and not self.outcome:
                raise ValidationError({"outcome": _("Bağlanma / itirmə üçün nəticə məcburidir.")})


class LeadActivity(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="activities")
    activity_type = models.CharField(max_length=24, choices=ActivityType.choices, default=ActivityType.NOTE)
    occurred_at = models.DateTimeField(default=timezone.now)
    body = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lead_activities",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        verbose_name_plural = "lead activities"

    def __str__(self):
        return f"{self.lead_id}:{self.activity_type}"


class Opportunity(models.Model):
    lead = models.ForeignKey(
        Lead,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="opportunities",
    )
    party = models.ForeignKey(
        "parties.Party",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="opportunities",
    )
    title = models.CharField(max_length=200)
    status = models.CharField(
        max_length=16,
        choices=OpportunityStatus.choices,
        default=OpportunityStatus.OPEN,
    )
    pipeline_stage = models.CharField(
        max_length=32, choices=PipelineStage.choices, default=PipelineStage.WORKING
    )
    expected_area = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    employee_count = models.PositiveIntegerField(null=True, blank=True)
    budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    outcome = models.CharField(max_length=32, choices=Outcome.choices, blank=True)
    outcome_note = models.TextField(blank=True)
    space = models.ForeignKey(
        "property.Space",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="opportunities",
    )
    notes = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_opportunities",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_opportunities",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "opportunities"

    def __str__(self):
        return self.title


class Offer(models.Model):
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="offers")
    space = models.ForeignKey(
        "property.Space",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="offers",
    )
    party = models.ForeignKey(
        "parties.Party",
        on_delete=models.PROTECT,
        related_name="offers",
    )
    status = models.CharField(max_length=24, choices=OfferStatus.choices, default=OfferStatus.DRAFT)
    rent_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valid_until = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    current_version = models.ForeignKey(
        "crm.OfferVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sent_offers",
    )
    sent_to = models.CharField(max_length=255, blank=True)
    lease = models.ForeignKey(
        "leases.Lease",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_offers",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.opportunity_id}:{self.status}"


class OfferVersion(models.Model):
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField(default=1)
    rent_rate_per_m2 = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("33.00"))
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("18.00"))
    area_m2 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    discount_note = models.CharField(max_length=255, blank=True)
    package_text = models.TextField(
        blank=True,
        default=(
            "Kommunal (internet xaric), təmizlik, təhlükəsizlik, reception, 7/24 xidmət daxildir."
        ),
    )
    monthly_rent_net = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    monthly_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    monthly_rent_gross = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    valid_until = models.DateField(null=True, blank=True)
    pdf_file = models.FileField(upload_to="crm/offers/%Y/%m/", blank=True)
    approval_request = models.ForeignKey(
        "workflows.ApprovalRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="offer_versions",
    )
    is_locked = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_offer_versions",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-version_number", "-id"]
        unique_together = [("offer", "version_number")]

    def __str__(self):
        return f"Offer {self.offer_id} v{self.version_number}"


class LeaseApplication(models.Model):
    offer = models.ForeignKey(
        Offer, null=True, blank=True, on_delete=models.SET_NULL, related_name="lease_applications"
    )
    offer_version = models.ForeignKey(
        OfferVersion,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lease_applications",
    )
    opportunity = models.ForeignKey(
        Opportunity,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lease_applications",
    )
    space = models.ForeignKey(
        "property.Space",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lease_applications",
    )
    lease = models.ForeignKey(
        "leases.Lease",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lease_applications",
    )
    status = models.CharField(
        max_length=40,
        choices=LeaseApplicationStatus.choices,
        default=LeaseApplicationStatus.DRAFT,
    )
    person_name = models.CharField(max_length=200, blank=True)
    tax_id = models.CharField(max_length=32, blank=True)
    legal_address = models.TextField(blank=True)
    actual_address = models.TextField(blank=True)
    floor_label = models.CharField(max_length=64, blank=True)
    space_label = models.CharField(max_length=128, blank=True)
    use_purpose = models.CharField(max_length=255, blank=True)
    rent_rate_per_m2 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    monthly_rent_net = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    deposit_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    rent_free_note = models.CharField(max_length=255, blank=True)
    cleaning_included = models.BooleanField(null=True, blank=True)
    tea_service_included = models.BooleanField(null=True, blank=True)
    lease_start = models.DateField(null=True, blank=True)
    lease_end = models.DateField(null=True, blank=True)
    bank_details = models.TextField(blank=True)
    fit_out_notes = models.TextField(blank=True)
    extra_notes = models.TextField(blank=True)
    signer_title_name = models.CharField(max_length=255, blank=True)
    is_legal_entity = models.BooleanField(default=True)
    attachment_checklist = models.JSONField(default=dict, blank=True)
    form_snapshot = models.JSONField(default=dict, blank=True)
    sales_notes = models.TextField(blank=True)
    accountant_notes = models.TextField(blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submitted_lease_applications",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_lease_applications",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_lease_applications",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"LeaseApp #{self.pk} ({self.status})"
