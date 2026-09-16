from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


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
    file = models.FileField(upload_to="documents/%Y/%m/", blank=True)
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
    published_at = models.DateField()

    class Meta:
        ordering = ["-published_at"]

    def __str__(self):
        return self.title


class DocumentVersion(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version_label = models.CharField(max_length=32)
    file = models.FileField(upload_to="documents/versions/%Y/%m/", blank=True)
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
