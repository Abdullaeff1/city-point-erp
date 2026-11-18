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


class ReportSnapshot(models.Model):
    """Daily executive KPI snapshot (M11) — not a DB backup substitute."""

    snapshot_date = models.DateField(db_index=True)
    company = models.ForeignKey(
        "residents.ResidentCompany",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="report_snapshots",
    )
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-snapshot_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot_date"],
                condition=models.Q(company__isnull=True),
                name="uniq_report_snapshot_date_all",
            ),
            models.UniqueConstraint(
                fields=["snapshot_date", "company"],
                condition=models.Q(company__isnull=False),
                name="uniq_report_snapshot_date_company",
            ),
        ]

    def __str__(self):
        co = self.company_id or "all"
        return f"snapshot:{self.snapshot_date}:{co}"
