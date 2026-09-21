import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

# Re-export org models so Django discovers them under apps.core
from apps.core.organization import Organization, OrgDepartment, OrgQueue, Team  # noqa: E402,F401


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDPrimaryModel(TimeStampedModel):
    """Optional UUID for external/integration-safe identifiers (not used as PK yet)."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)

    class Meta:
        abstract = True


class ActorMixin(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_created",
    )

    class Meta:
        abstract = True
