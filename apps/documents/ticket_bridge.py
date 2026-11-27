"""Register ticket attachments into the canonical Document archive (D08).

Operators keep uploading from ticket / portal screens. Each attachment dual-writes a
``Document`` (``ticket`` FK + sensitivity) so Management can find it in ``/erp/documents/``.
Audience is explicit: resident-visible vs internal — a shared ticket never publishes
internal files.
"""

from __future__ import annotations

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.services import DomainError
from apps.documents.models import Document, DocumentSensitivity
from apps.documents.services import DocumentService
from apps.documents.validation import TICKET_ALLOWED_EXTENSIONS

DOC_TYPE_TICKET_ATTACHMENT = "ticket_attachment"


def _ticket_type():
    return DocumentService.ensure_type(
        DOC_TYPE_TICKET_ATTACHMENT,
        "Sorğu əlavəsi",
        default_sensitivity=DocumentSensitivity.INTERNAL,
    )


def _read_upload(upload) -> tuple[bytes, str]:
    name = getattr(upload, "name", "") or "attachment.bin"
    if hasattr(upload, "open"):
        try:
            upload.open("rb")
        except Exception:  # noqa: BLE001
            pass
    data = upload.read()
    if hasattr(upload, "seek"):
        try:
            upload.seek(0)
        except Exception:  # noqa: BLE001
            pass
    return data or b"", name.rsplit("/", 1)[-1]


@transaction.atomic
def register_ticket_attachment(
    *,
    ticket,
    upload,
    actor=None,
    visible_to_resident: bool = False,
    title: str = "",
) -> tuple:
    """Create TicketAttachment + linked Document. Returns ``(attachment, document)``."""
    from apps.tickets.models import TicketAttachment

    if not upload:
        raise DomainError(_("Fayl seçilməyib."))
    data, raw_name = _read_upload(upload)
    if not data:
        raise DomainError(_("Fayl boşdur."))

    company = getattr(ticket, "company", None)
    visible = bool(visible_to_resident)
    sens = (
        DocumentSensitivity.PUBLIC_RESIDENT
        if visible
        else DocumentSensitivity.INTERNAL
    )
    doc_title = (title or "").strip() or f"{ticket.code} — {raw_name}"[:200]
    document = DocumentService.upload_new(
        title=doc_title,
        uploaded_file=ContentFile(data, name=raw_name),
        company=company,
        document_type=_ticket_type(),
        created_by=actor,
        ticket=ticket,
        visible_to_resident=visible,
        sensitivity=sens,
        allowed_extensions=TICKET_ALLOWED_EXTENSIONS,
        content_check=False,
    )
    attachment = TicketAttachment(
        ticket=ticket,
        document=document,
        visible_to_resident=visible,
        uploaded_by=actor if getattr(actor, "pk", None) else None,
    )
    attachment.file.save(raw_name, ContentFile(data), save=False)
    attachment.save()
    return attachment, document


@transaction.atomic
def link_legacy_ticket_attachment(attachment, *, actor=None) -> Document | None:
    """Idempotent: ensure a legacy TicketAttachment has a Document. Returns Document or None if no file."""
    from apps.tickets.models import TicketAttachment

    attachment = TicketAttachment.objects.select_related("ticket", "document").get(pk=attachment.pk)
    if attachment.document_id:
        return attachment.document
    if not attachment.file:
        return None
    try:
        attachment.file.open("rb")
        data = attachment.file.read()
        attachment.file.close()
    except Exception:  # noqa: BLE001
        return None
    if not data:
        return None
    raw_name = attachment.file.name.rsplit("/", 1)[-1] or "attachment.bin"
    ticket = attachment.ticket
    visible = bool(attachment.visible_to_resident)
    sens = (
        DocumentSensitivity.PUBLIC_RESIDENT
        if visible
        else DocumentSensitivity.INTERNAL
    )
    document = DocumentService.upload_new(
        title=f"{ticket.code} — {raw_name}"[:200],
        uploaded_file=ContentFile(data, name=raw_name),
        company=getattr(ticket, "company", None),
        document_type=_ticket_type(),
        created_by=actor or getattr(attachment, "uploaded_by", None),
        ticket=ticket,
        visible_to_resident=visible,
        sensitivity=sens,
        allowed_extensions=TICKET_ALLOWED_EXTENSIONS,
        content_check=False,
    )
    attachment.document = document
    attachment.save(update_fields=["document"])
    return document
