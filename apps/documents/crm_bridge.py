"""Register CRM offer PDFs into the canonical Document archive (D08).

One ``Document`` per ``Offer``; each ``OfferVersion`` PDF becomes a ``DocumentVersion``
with label matching the offer version number. Explicit portal share pins
``portal_shared_version`` so a later draft (v2) does not replace the shared v1 file.
"""

from __future__ import annotations

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.services import DomainError
from apps.documents.models import Document, DocumentSensitivity, DocumentVersion
from apps.documents.services import DocumentService

DOC_TYPE_OFFER_PDF = "offer_pdf"


def _offer_type():
    return DocumentService.ensure_type(
        DOC_TYPE_OFFER_PDF,
        "CRM təklif PDF",
        default_sensitivity=DocumentSensitivity.CONFIDENTIAL,
    )


def _company_for_offer(offer):
    party = getattr(offer, "party", None)
    company_id = getattr(party, "legacy_resident_company_id", None) if party else None
    if not company_id:
        return None
    from apps.residents.models import ResidentCompany

    return ResidentCompany.objects.filter(pk=company_id).first()


def document_for_offer(offer) -> Document | None:
    return (
        Document.objects.filter(offer_id=offer.pk, document_type__code=DOC_TYPE_OFFER_PDF)
        .order_by("id")
        .first()
    )


def version_for_offer_version(document: Document, offer_version) -> DocumentVersion | None:
    label = str(offer_version.version_number)
    return document.versions.filter(version_label=label).order_by("id").first()


@transaction.atomic
def register_offer_version_pdf(offer_version, *, actor=None) -> Document | None:
    """Ensure OfferVersion.pdf_file is mirrored as Document(+Version). Idempotent per version label."""
    from apps.crm.models import OfferVersion

    version = OfferVersion.objects.select_related("offer", "offer__party").get(pk=offer_version.pk)
    if not version.pdf_file:
        return None
    offer = version.offer
    try:
        version.pdf_file.open("rb")
        data = version.pdf_file.read()
        version.pdf_file.close()
    except Exception:  # noqa: BLE001
        return None
    if not data:
        return None

    name = f"offer_{offer.pk}_v{version.version_number}.pdf"
    label = str(version.version_number)
    company = _company_for_offer(offer)
    existing = document_for_offer(offer)
    if existing is not None:
        already = version_for_offer_version(existing, version)
        if already is not None and already.file:
            return existing
        DocumentService.add_version(
            existing,
            uploaded_file=ContentFile(data, name=name),
            created_by=actor or version.created_by,
            label=label,
        )
        return existing

    document = DocumentService.upload_new(
        title=f"Təklif #{offer.pk}",
        uploaded_file=ContentFile(data, name=name),
        company=company,
        document_type=_offer_type(),
        created_by=actor or version.created_by,
        party=offer.party,
        offer=offer,
        visible_to_resident=False,
        sensitivity=DocumentSensitivity.CONFIDENTIAL,
    )
    # Align first DocumentVersion label with offer version number.
    ver = DocumentService.current_version(document)
    if ver and ver.version_label != label:
        ver.version_label = label
        ver.save(update_fields=["version_label"])
        document.version = label
        document.save(update_fields=["version", "updated_at"])
    return document


@transaction.atomic
def share_offer_version_with_resident(offer_version, *, actor) -> Document:
    """Pin portal_shared_version to this offer version's archive file (drafts do not auto-promote)."""
    document = register_offer_version_pdf(offer_version, actor=actor)
    if document is None:
        raise DomainError(_("Təklif PDF arxivə yazılmayıb."))
    document.refresh_from_db()
    company = document.company or _company_for_offer(offer_version.offer)
    if company is None:
        raise DomainError(_("Təklif rezident şirkətə bağlı deyil — portala paylaşmaq olmaz."))
    if document.company_id is None:
        document.company = company
        document.save(update_fields=["company", "updated_at"])
    ver = version_for_offer_version(document, offer_version)
    if ver is None:
        raise DomainError(_("Bu təklif versiyası üçün arxiv faylı yoxdur."))
    return DocumentService.share_version_with_resident(
        document, ver, actor=actor, company=company
    )
