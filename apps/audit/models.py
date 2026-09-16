from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class AuditLog(models.Model):
    created_at = models.DateTimeField(default=timezone.now, db_index=True, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=64, db_index=True)
    entity_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    entity_id = models.PositiveBigIntegerField(null=True, blank=True)
    entity = GenericForeignKey("entity_type", "entity_id")
    object_repr = models.CharField(max_length=255, blank=True)
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    source = models.CharField(max_length=64, blank=True, default="erp")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
        ]

    def __str__(self):
        return f"{self.action} {self.object_repr}"
