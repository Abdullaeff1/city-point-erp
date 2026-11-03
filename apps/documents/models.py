from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
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
    (DOCUMENT_TYPE_OTHER, "Digər"),
)


class DocumentType(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    retention_days = models.PositiveIntegerField(null=True, blank=True)
    requires_approval = models.BooleanField(default=False)

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
    version = models.CharField(max_length=32, blank=True)
    size_label = models.CharField(max_length=32, blank=True)
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
