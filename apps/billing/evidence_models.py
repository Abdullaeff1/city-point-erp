"""Resident payment instruction evidence (Decision 05).

Evidence is a *claim* uploaded by the resident company — it never changes the invoice balance.
Only Finance-verified ``Payment`` rows do; ``payment`` is linked after that happens.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class EvidenceStatus(models.TextChoices):
    PENDING_REVIEW = "pending_review", _("Yoxlama gözləyir")
    NEEDS_CLARIFICATION = "needs_clarification", _("Dəqiqləşdirmə lazımdır")
    LINKED = "linked", _("Ödənişə bağlanıb")
    CANCELLED = "cancelled", _("Ləğv edilib")


class InvoicePaymentEvidence(models.Model):
    invoice = models.ForeignKey(
        "billing.Invoice",
        on_delete=models.PROTECT,
        related_name="payment_evidence",
    )
    company = models.ForeignKey(
        "residents.ResidentCompany",
        on_delete=models.PROTECT,
        related_name="payment_evidence",
    )
    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.PROTECT,
        related_name="payment_evidence",
    )
    version = models.ForeignKey(
        "documents.DocumentVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payment_evidence",
    )
    status = models.CharField(
        max_length=24,
        choices=EvidenceStatus.choices,
        default=EvidenceStatus.PENDING_REVIEW,
        db_index=True,
    )
    payment = models.ForeignKey(
        "billing.Payment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="evidence",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payment_evidence_uploaded",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payment_evidence_reviewed",
    )
    file_hash = models.CharField(max_length=64, blank=True, db_index=True)
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"evidence:{self.pk}:{self.invoice_id}:{self.status}"
