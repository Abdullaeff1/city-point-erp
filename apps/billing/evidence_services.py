"""Accountant ↔ resident financial documents (Decision 05).

* Finance uploads the official invoice document; the resident only sees a version Finance
  explicitly shared (``Document.portal_shared_version``).
* The resident uploads a payment instruction / evidence. It is a *claim*: it never records a
  ``Payment`` and never touches the invoice balance or the journal. Finance verifies the cash and
  records it separately (``record_incoming_payment_verified`` / existing ``record_payment``), then
  links the evidence to that Payment.
"""

from __future__ import annotations

import hashlib

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import Role
from apps.audit.services import log_action
from apps.billing.evidence_models import EvidenceStatus, InvoicePaymentEvidence
from apps.billing.models import Invoice, InvoiceStatus, Payment
from apps.core.services import DomainError
from apps.documents.models import Document, DocumentSensitivity, DocumentVersion
from apps.documents.services import DocumentService
from apps.finance.access import can_mutate_finance

DOC_TYPE_INVOICE_OFFICIAL = "invoice_official"
DOC_TYPE_PAYMENT_INSTRUCTION = "payment_instruction"

OPEN_EVIDENCE_STATUSES = (EvidenceStatus.PENDING_REVIEW, EvidenceStatus.NEEDS_CLARIFICATION)


def invoice_company_id(invoice: Invoice) -> int | None:
    """Resident company the invoice belongs to (via Party dual-write link)."""
    party = getattr(invoice, "party", None)
    return getattr(party, "legacy_resident_company_id", None)


def _require_accountant(actor) -> None:
    if not can_mutate_finance(actor):
        raise DomainError(_("Bu əməliyyat yalnız mühasib üçündür."))


def _file_sha256(uploaded_file) -> str:
    try:
        uploaded_file.seek(0)
        data = uploaded_file.read()
        uploaded_file.seek(0)
        return hashlib.sha256(data).hexdigest() if data else ""
    except Exception:  # noqa: BLE001
        return ""


def _official_type():
    return DocumentService.ensure_type(
        DOC_TYPE_INVOICE_OFFICIAL,
        "Rəsmi faktura",
        default_sensitivity=DocumentSensitivity.CONFIDENTIAL,
    )


def _instruction_type():
    return DocumentService.ensure_type(
        DOC_TYPE_PAYMENT_INSTRUCTION,
        "Ödəniş sənədi",
        default_sensitivity=DocumentSensitivity.CONFIDENTIAL,
    )


def official_documents_for(invoice: Invoice):
    """Finance official invoice documents attached to this invoice (newest first)."""
    return Document.objects.filter(
        invoice=invoice, document_type__code=DOC_TYPE_INVOICE_OFFICIAL
    ).order_by("-published_at", "-id")


@transaction.atomic
def upload_official_invoice_document(invoice: Invoice, file, actor, *, share: bool = False) -> Document:
    """Finance uploads the official invoice file; a second upload becomes a new draft version.

    ``share=False`` keeps it internal (Finance-only). Sharing is explicit, per version.
    """
    _require_accountant(actor)
    invoice = Invoice.objects.select_related("party").get(pk=invoice.pk)
    if invoice.status == InvoiceStatus.VOID:
        raise DomainError(_("Ləğv olunmuş fakturaya sənəd əlavə olunmur."))
    company_id = invoice_company_id(invoice)
    if share and not company_id:
        raise DomainError(_("Faktura rezident şirkətə bağlı deyil — portala paylaşmaq olmaz."))

    existing = official_documents_for(invoice).first()
    if existing is not None:
        DocumentService.add_version(existing, uploaded_file=file, created_by=actor)
        document = existing
    else:
        from apps.residents.models import ResidentCompany

        company = ResidentCompany.objects.filter(pk=company_id).first() if company_id else None
        document = DocumentService.upload_new(
            title=f"Rəsmi faktura {invoice.code}",
            uploaded_file=file,
            company=company,
            document_type=_official_type(),
            created_by=actor,
            party=invoice.party,
            invoice=invoice,
            sensitivity=DocumentSensitivity.CONFIDENTIAL,
        )
    if share:
        version = DocumentService.current_version(document)
        share_invoice_document(document, version, actor)
        document.refresh_from_db()
    return document


@transaction.atomic
def share_invoice_document(document: Document, version: DocumentVersion, actor) -> Document:
    """Finance shares one explicit version of an invoice document with the resident company."""
    _require_accountant(actor)
    if not document.invoice_id:
        raise DomainError(_("Sənəd fakturaya bağlı deyil."))
    if document.company is None:
        raise DomainError(_("Sənədin rezident şirkəti yoxdur."))
    if invoice_company_id(document.invoice) != document.company_id:
        raise DomainError(_("Sənəd şirkəti faktura şirkəti ilə üst-üstə düşmür."))
    return DocumentService.share_version_with_resident(
        document, version, actor=actor, company=document.company
    )


def _notify_finance(evidence: InvoicePaymentEvidence) -> int:
    """Notify every active Accountant once per evidence (key dedupes per user)."""
    from django.contrib.auth import get_user_model

    from apps.comms.services import notify_in_app

    User = get_user_model()
    message = _("Yeni ödəniş sənədi: %(inv)s · %(company)s") % {
        "inv": evidence.invoice.code,
        "company": evidence.company.name,
    }
    count = 0
    for user in User.objects.filter(role=Role.ACCOUNTANT, is_active=True).order_by("pk"):
        notify_in_app(
            user=user,
            message=message[:255],
            event_key=f"payment.evidence.{evidence.pk}",
        )
        count += 1
    return count


def notify_finance_of_evidence(evidence: InvoicePaymentEvidence) -> int:
    return _notify_finance(evidence)


@transaction.atomic
def resident_upload_payment_instruction(
    invoice: Invoice, file, actor, company
) -> InvoicePaymentEvidence:
    """Resident uploads a payment document for an invoice of the selected company.

    Never records a Payment: balance, status and journal stay untouched until Finance verifies.
    """
    from apps.accounts.portal_scope import eligible_company_ids_for

    if actor is None or not getattr(actor, "is_authenticated", False):
        raise DomainError(_("İstifadəçi tələb olunur."))
    if actor.role != Role.RESIDENT_USER:
        raise DomainError(_("Ödəniş sənədini yalnız rezident istifadəçi yükləyə bilər."))
    if company is None or company.pk not in set(eligible_company_ids_for(actor)):
        raise DomainError(_("Bu şirkət üçün icazəniz yoxdur."))

    invoice = Invoice.objects.select_for_update().select_related("party").get(pk=invoice.pk)
    if invoice_company_id(invoice) != company.pk:
        raise DomainError(_("Faktura seçilmiş şirkətə aid deyil."))
    if invoice.status not in (InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE):
        raise DomainError(_("Yalnız açıq (ödənilməmiş) faktura üçün sənəd yüklənə bilər."))

    digest = _file_sha256(file)
    if digest:
        duplicate = (
            InvoicePaymentEvidence.objects.filter(
                invoice=invoice,
                company=company,
                file_hash=digest,
                status__in=OPEN_EVIDENCE_STATUSES,
            )
            .order_by("-id")
            .first()
        )
        if duplicate is not None:
            # Double submit of the same file: same evidence, no second notification.
            return duplicate

    document = DocumentService.upload_new(
        title=f"Ödəniş sənədi {invoice.code}",
        uploaded_file=file,
        company=company,
        document_type=_instruction_type(),
        created_by=actor,
        party=invoice.party,
        invoice=invoice,
        visible_to_resident=False,
        sensitivity=DocumentSensitivity.CONFIDENTIAL,
    )
    evidence = InvoicePaymentEvidence.objects.create(
        invoice=invoice,
        company=company,
        document=document,
        version=DocumentService.current_version(document),
        status=EvidenceStatus.PENDING_REVIEW,
        uploaded_by=actor,
        file_hash=digest,
    )
    log_action(
        action="billing.payment_evidence_uploaded",
        actor=actor,
        entity=evidence,
        new_values={"invoice_id": invoice.pk, "company_id": company.pk, "document_id": document.pk},
        source="portal",
    )
    _notify_finance(evidence)
    return evidence


@transaction.atomic
def link_evidence_to_payment(
    evidence: InvoicePaymentEvidence, payment: Payment, actor
) -> InvoicePaymentEvidence:
    """Attach an already-recorded Payment to the evidence. Creates NO Payment / journal."""
    _require_accountant(actor)
    locked = InvoicePaymentEvidence.objects.select_for_update().get(pk=evidence.pk)
    if locked.payment_id == payment.pk and locked.status == EvidenceStatus.LINKED:
        return locked
    if locked.invoice_id != payment.invoice_id:
        raise DomainError(_("Ödəniş və sübut eyni fakturaya aid olmalıdır."))
    if locked.status == EvidenceStatus.CANCELLED:
        raise DomainError(_("Ləğv edilmiş sübut ödənişə bağlana bilməz."))
    if locked.status == EvidenceStatus.LINKED:
        raise DomainError(_("Sübut artıq başqa ödənişə bağlıdır."))
    locked.payment = payment
    locked.status = EvidenceStatus.LINKED
    locked.reviewed_by = actor
    locked.reviewed_at = timezone.now()
    locked.save(update_fields=["payment", "status", "reviewed_by", "reviewed_at"])
    log_action(
        action="billing.payment_evidence_linked",
        actor=actor,
        entity=locked,
        new_values={"payment_id": payment.pk, "invoice_id": locked.invoice_id},
        source="finance",
    )
    evidence.payment = payment
    evidence.status = locked.status
    return locked


@transaction.atomic
def set_evidence_status(
    evidence: InvoicePaymentEvidence, status: str, actor, *, note: str = ""
) -> InvoicePaymentEvidence:
    """Finance asks for clarification or cancels an open evidence row."""
    _require_accountant(actor)
    if status not in (EvidenceStatus.NEEDS_CLARIFICATION, EvidenceStatus.CANCELLED):
        raise DomainError(_("Yanlış status."))
    locked = InvoicePaymentEvidence.objects.select_for_update().get(pk=evidence.pk)
    if locked.status not in OPEN_EVIDENCE_STATUSES:
        raise DomainError(_("Yalnız açıq sübutun statusu dəyişdirilə bilər."))
    locked.status = status
    locked.note = (note or "")[:500]
    locked.reviewed_by = actor
    locked.reviewed_at = timezone.now()
    locked.save(update_fields=["status", "note", "reviewed_by", "reviewed_at"])
    log_action(
        action="billing.payment_evidence_status",
        actor=actor,
        entity=locked,
        new_values={"status": status, "note": locked.note},
        source="finance",
    )
    evidence.status = locked.status
    evidence.note = locked.note
    return locked
