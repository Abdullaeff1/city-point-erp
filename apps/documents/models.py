from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.documents.storage import private_document_storage

DOCUMENT_TYPE_LEASE_CONTRACT = "lease_contract"
DOCUMENT_TYPE_LEASE_AMENDMENT = "lease_amendment"
DOCUMENT_TYPE_VOEN = "voen_certificate"
DOCUMENT_TYPE_CHARTER = "charter"
DOCUMENT_TYPE_JUSTICE = "justice_registration"
DOCUMENT_TYPE_POWER_OF_ATTORNEY = "power_of_attorney"
DOCUMENT_TYPE_BANK_CERTIFICATE = "bank_certificate"
DOCUMENT_TYPE_COMPANY_EXTRACT = "company_extract"
DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED = "lease_application_signed"
DOCUMENT_TYPE_INCOMING_LETTER = "incoming_letter"
DOCUMENT_TYPE_OUTGOING_LETTER = "outgoing_letter"
DOCUMENT_TYPE_OTHER = "other"

SEED_DOCUMENT_TYPES = (
    (DOCUMENT_TYPE_LEASE_CONTRACT, "İcarə müqaviləsi"),
    (DOCUMENT_TYPE_LEASE_AMENDMENT, "İcarə əlavəsi"),
    (DOCUMENT_TYPE_VOEN, "VÖEN şəhadətnaməsi"),
    (DOCUMENT_TYPE_CHARTER, "Nizamnamə"),
    (DOCUMENT_TYPE_JUSTICE, "Ədliyyə qeydiyyatı"),
    (DOCUMENT_TYPE_POWER_OF_ATTORNEY, "Etibarnamə"),
    (DOCUMENT_TYPE_BANK_CERTIFICATE, "Bank arayışı"),
    (DOCUMENT_TYPE_COMPANY_EXTRACT, "Reyestrdən çıxarış"),
    (DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED, "İmzalanmış müraciət forması"),
    (DOCUMENT_TYPE_INCOMING_LETTER, "Daxil olan məktub"),
    (DOCUMENT_TYPE_OUTGOING_LETTER, "Gedən məktub"),
    (DOCUMENT_TYPE_OTHER, "Digər"),
)

# Default retention (days) — hüquqi təsdiq gözlənilən siyasət scaffold.
DEFAULT_RETENTION_DAYS = {
    DOCUMENT_TYPE_LEASE_CONTRACT: 3650,  # ~10 il
    DOCUMENT_TYPE_LEASE_AMENDMENT: 3650,
    DOCUMENT_TYPE_VOEN: 1825,
    DOCUMENT_TYPE_CHARTER: 1825,
    DOCUMENT_TYPE_JUSTICE: 1825,
    DOCUMENT_TYPE_POWER_OF_ATTORNEY: 1095,
    DOCUMENT_TYPE_BANK_CERTIFICATE: 365,
    DOCUMENT_TYPE_COMPANY_EXTRACT: 365,
    DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED: 3650,
    DOCUMENT_TYPE_INCOMING_LETTER: 3650,  # retention policy pending City Point legal confirm
    DOCUMENT_TYPE_OUTGOING_LETTER: 3650,
    DOCUMENT_TYPE_OTHER: 730,
}


class CorrespondenceDirection(models.TextChoices):
    INCOMING = "incoming", _("Daxil olan")
    OUTGOING = "outgoing", _("Gedən")


class CorrespondenceStatus(models.TextChoices):
    REGISTERED = "registered", _("Qeydiyyatda")
    ROUTED = "routed", _("Yönləndirilib")
    IN_PROGRESS = "in_progress", _("İşlənir")
    PENDING_APPROVAL = "pending_approval", _("Təsdiq gözləyir")
    APPROVED = "approved", _("Təsdiqlənib")
    DISPATCHED = "dispatched", _("Göndərilib")
    CLOSED = "closed", _("Bağlı")


class DocumentSensitivity(models.TextChoices):
    """Vahid məxfilik: müqavilə / şəxsiyyət / əməliyyat / daxili."""

    PUBLIC_RESIDENT = "public_resident", _("Portala açıq")
    INTERNAL = "internal", _("Daxili (staff)")
    CONFIDENTIAL = "confidential", _("Məxfi (hüquqi/maliyyə)")
    RESTRICTED = "restricted", _("Məhdud (şəxsiyyət)")


class DocumentType(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    retention_days = models.PositiveIntegerField(null=True, blank=True)
    requires_approval = models.BooleanField(default=False)
    default_sensitivity = models.CharField(
        max_length=24,
        choices=DocumentSensitivity.choices,
        default=DocumentSensitivity.CONFIDENTIAL,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Document(models.Model):
    title = models.CharField(max_length=200)
    document_type = models.ForeignKey(
        DocumentType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    file = models.FileField(
        upload_to="documents/%Y/%m/",
        blank=True,
        storage=private_document_storage,
    )
    file_type = models.CharField(max_length=16, default="PDF")
    content_type = models.CharField(max_length=128, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    version = models.CharField(max_length=32, blank=True)
    size_label = models.CharField(max_length=32, blank=True)
    sensitivity = models.CharField(
        max_length=24,
        choices=DocumentSensitivity.choices,
        default=DocumentSensitivity.CONFIDENTIAL,
        db_index=True,
    )
    company = models.ForeignKey(
        "residents.ResidentCompany",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    space = models.ForeignKey(
        "property.Space", null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )
    lease = models.ForeignKey(
        "leases.Lease",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    parent_document = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="amendments",
    )
    # --- Phase 10 correspondence / kargüzarlıq (optional; vault docs leave blank) ---
    direction = models.CharField(
        max_length=16,
        choices=CorrespondenceDirection.choices,
        blank=True,
        db_index=True,
    )
    registry_number = models.CharField(
        max_length=32,
        blank=True,
        db_index=True,
        verbose_name=_("Daxili qeydiyyat №"),
    )
    external_reference = models.CharField(
        max_length=120,
        blank=True,
        verbose_name=_("Göndərənin istinadı"),
    )
    received_at = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Qəbul / daxilolma tarixi"),
    )
    correspondence_status = models.CharField(
        max_length=24,
        choices=CorrespondenceStatus.choices,
        blank=True,
        db_index=True,
    )
    routed_department = models.ForeignKey(
        "tickets.TicketDepartment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="routed_documents",
    )
    related_correspondence = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="linked_correspondence",
        help_text=_("Incoming↔outgoing reply pair"),
    )
    party = models.ForeignKey(
        "parties.Party",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    ticket = models.ForeignKey(
        "tickets.Ticket",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    work_order = models.ForeignKey(
        "maintenance.WorkOrder",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    purchase_request = models.ForeignKey(
        "procurement.PurchaseRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    purchase_order = models.ForeignKey(
        "procurement.PurchaseOrder",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    invoice = models.ForeignKey(
        "billing.Invoice",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    published_at = models.DateField()
    document_date = models.DateField(null=True, blank=True, verbose_name=_("Sənəd tarixi"))
    visible_to_resident = models.BooleanField(
        default=False,
        verbose_name=_("Portala görünən"),
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_documents",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_documents",
    )

    class Meta:
        ordering = ["-published_at", "-id"]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        errors = {}
        if self.parent_document_id:
            if self.parent_document_id == self.pk:
                errors["parent_document"] = _("Sənəd özünün parent-i ola bilməz.")
            elif self.parent_document and self.company_id and self.parent_document.company_id != self.company_id:
                errors["parent_document"] = _("Parent sənəd eyni şirkətə aid olmalıdır.")
            type_code = getattr(self.document_type, "code", None) if self.document_type_id else None
            if type_code == DOCUMENT_TYPE_LEASE_AMENDMENT:
                parent = self.parent_document
                parent_code = getattr(parent.document_type, "code", None) if parent else None
                if parent_code != DOCUMENT_TYPE_LEASE_CONTRACT:
                    errors["parent_document"] = _("Əlavə yalnız əsas müqaviləyə bağlana bilər.")
                if parent and getattr(parent.document_type, "code", None) == DOCUMENT_TYPE_LEASE_AMENDMENT:
                    errors["parent_document"] = _("Parent özü əlavə ola bilməz.")
        elif self.document_type_id and getattr(self.document_type, "code", None) == DOCUMENT_TYPE_LEASE_AMENDMENT:
            errors["parent_document"] = _("İcarə əlavəsi üçün əsas müqavilə seçilməlidir.")

        if self.lease_id and self.company_id:
            lease = self.lease
            party = getattr(lease, "party", None) if lease else None
            linked = getattr(party, "legacy_resident_company_id", None) if party else None
            if linked and linked != self.company_id:
                errors["lease"] = _("İcarə bu şirkətə aid deyil.")
            space = getattr(lease, "space", None) if lease else None
            if space and space.resident_id and space.resident_id != self.company_id:
                errors["lease"] = _("İcarənin sahəsi bu şirkətə aid deyil.")

        if errors:
            raise ValidationError(errors)

    def delete(self, using=None, keep_parents=False):
        from django.db import transaction

        if self.amendments.exists():
            raise ValidationError(_("Əlavəsi olan müqavilə silinə bilməz."))
        name = self.file.name if self.file else ""
        storage = self.file.storage if self.file else None
        result = super().delete(using=using, keep_parents=keep_parents)

        def _cleanup():
            if name and storage:
                try:
                    storage.delete(name)
                except Exception:
                    pass

        transaction.on_commit(_cleanup)
        return result


class DocumentVersion(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version_label = models.CharField(max_length=32)
    file = models.FileField(
        upload_to="documents/versions/%Y/%m/",
        blank=True,
        storage=private_document_storage,
    )
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="document_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_current = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Document version")

    def __str__(self):
        return f"{self.document_id}@{self.version_label}"


class CorrespondenceNumberSequence(models.Model):
    """Yearly counter for official IN-/OUT- registry numbers (concurrent-safe)."""

    direction = models.CharField(max_length=16, choices=CorrespondenceDirection.choices)
    year = models.PositiveIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("direction", "year")

    def __str__(self):
        return f"{self.direction}:{self.year}:{self.last_value}"


class DocumentDispatch(models.Model):
    """Manual dispatch record for an approved outgoing correspondence version."""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="dispatches")
    version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.PROTECT,
        related_name="dispatches",
    )
    recipient = models.CharField(max_length=255)
    channel = models.CharField(
        max_length=32,
        default="manual",
        help_text=_("manual|courier|hand|post — no external email required"),
    )
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="document_dispatches",
    )
    dispatched_at = models.DateTimeField(default=timezone.now)
    notes = models.CharField(max_length=255, blank=True)
    operation_key = models.CharField(max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-dispatched_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "operation_key"],
                name="uniq_document_dispatch_operation_key",
                condition=~models.Q(operation_key=""),
            )
        ]

    def __str__(self):
        return f"dispatch:{self.document_id}:v{self.version_id}"
