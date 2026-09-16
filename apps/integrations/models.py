from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class SyncStatus(models.TextChoices):
    PENDING = "pending", _("Gözləyir")
    SUCCESS = "success", _("Uğurlu")
    ERROR = "error", _("Xəta")
    DEAD = "dead", _("Dead-letter")


class ExternalIdentity(TimeStampedModel):
    system = models.CharField(max_length=64, db_index=True)
    external_id = models.CharField(max_length=128)
    entity_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    entity_id = models.PositiveBigIntegerField()
    entity = GenericForeignKey("entity_type", "entity_id")
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=16, choices=SyncStatus.choices, default=SyncStatus.PENDING)
    last_error = models.TextField(blank=True)

    class Meta:
        unique_together = ("system", "external_id")
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def __str__(self):
        return f"{self.system}:{self.external_id}"


class SyncLog(TimeStampedModel):
    system = models.CharField(max_length=64, db_index=True)
    operation = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=SyncStatus.choices)
    request_payload = models.JSONField(null=True, blank=True)
    response_payload = models.JSONField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    correlation_id = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
