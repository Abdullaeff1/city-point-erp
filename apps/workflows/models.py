from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", _("Gözləyir")
    APPROVED = "approved", _("Təsdiqlənib")
    REJECTED = "rejected", _("Rədd edilib")
    CANCELLED = "cancelled", _("Ləğv edilib")


class ApprovalRequest(TimeStampedModel):
    workflow_code = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=16, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approval_requests",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approval_decisions",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)
    entity_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    entity_id = models.PositiveBigIntegerField(null=True, blank=True)
    entity = GenericForeignKey("entity_type", "entity_id")
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.workflow_code}:{self.status}"
