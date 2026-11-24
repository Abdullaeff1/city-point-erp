"""Phase 10 kargüzarlıq — register, route, reply, dispatch (manual)."""

from __future__ import annotations

import uuid
from datetime import date

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit.services import log_action
from apps.core.services import DomainError
from apps.documents.models import (
    DOCUMENT_TYPE_INCOMING_LETTER,
    DOCUMENT_TYPE_OUTGOING_LETTER,
    DEFAULT_RETENTION_DAYS,
    CorrespondenceDirection,
    CorrespondenceNumberSequence,
    CorrespondenceStatus,
    Document,
    DocumentDispatch,
    DocumentType,
    DocumentVersion,
)
from apps.documents.services import DocumentService, WF_DOCUMENT_APPROVE
from apps.rbac.services import user_has_permission
from apps.workflows.models import ApprovalRequest, ApprovalStatus


def _can_edit_documents(user) -> bool:
    return bool(user and user_has_permission(user, "document.edit"))


def ensure_correspondence_types() -> tuple[DocumentType, DocumentType]:
    incoming, _ = DocumentType.objects.get_or_create(
        code=DOCUMENT_TYPE_INCOMING_LETTER,
        defaults={
            "name": "Daxil olan məktub",
            "retention_days": DEFAULT_RETENTION_DAYS[DOCUMENT_TYPE_INCOMING_LETTER],
            "requires_approval": False,
            "default_sensitivity": "confidential",
        },
    )
    outgoing, _ = DocumentType.objects.get_or_create(
        code=DOCUMENT_TYPE_OUTGOING_LETTER,
        defaults={
            "name": "Gedən məktub",
            "retention_days": DEFAULT_RETENTION_DAYS[DOCUMENT_TYPE_OUTGOING_LETTER],
            "requires_approval": True,
            "default_sensitivity": "confidential",
        },
    )
    if not outgoing.requires_approval:
        outgoing.requires_approval = True
        outgoing.save(update_fields=["requires_approval"])
    return incoming, outgoing


@transaction.atomic
def allocate_registry_number(*, direction: str, when: date | None = None) -> str:
    """Official format: IN-YYYY-NNNN / OUT-YYYY-NNNN (City Point interim rule)."""
    if direction not in (
        CorrespondenceDirection.INCOMING,
        CorrespondenceDirection.OUTGOING,
    ):
        raise DomainError("Korrespondensiya istiqaməti yanlışdır.")
    year = (when or timezone.localdate()).year
    seq, _ = CorrespondenceNumberSequence.objects.select_for_update().get_or_create(
        direction=direction,
        year=year,
        defaults={"last_value": 0},
    )
    seq.last_value += 1
    seq.save(update_fields=["last_value"])
    prefix = "IN" if direction == CorrespondenceDirection.INCOMING else "OUT"
    return f"{prefix}-{year}-{seq.last_value:04d}"


@transaction.atomic
def register_incoming_letter(
    *,
    title: str,
    uploaded_file,
    actor,
    company=None,
    lease=None,
    party=None,
    letter_date: date | None = None,
    received_at: date | None = None,
    external_reference: str = "",
    routed_department=None,
    ticket=None,
    work_order=None,
    purchase_request=None,
    purchase_order=None,
    invoice=None,
) -> Document:
    if not _can_edit_documents(actor):
        raise DomainError("Korrespondensiya qeydiyyatı icazəniz yoxdur.")
    incoming_type, _ = ensure_correspondence_types()
    letter_date = letter_date or timezone.localdate()
    received_at = received_at or timezone.localdate()
    registry = allocate_registry_number(
        direction=CorrespondenceDirection.INCOMING, when=received_at
    )
    doc = DocumentService.upload_new(
        title=title,
        uploaded_file=uploaded_file,
        company=company,
        lease=lease,
        document_type=incoming_type,
        created_by=actor,
        document_date=letter_date,
        visible_to_resident=False,
    )
    doc.direction = CorrespondenceDirection.INCOMING
    doc.registry_number = registry
    doc.external_reference = (external_reference or "").strip()[:120]
    doc.received_at = received_at
    doc.published_at = received_at
    doc.party = party
    doc.ticket = ticket
    doc.work_order = work_order
    doc.purchase_request = purchase_request
    doc.purchase_order = purchase_order
    doc.invoice = invoice
    doc.routed_department = routed_department
    doc.correspondence_status = (
        CorrespondenceStatus.ROUTED if routed_department else CorrespondenceStatus.REGISTERED
    )
    doc.save()
    log_action(
        action="correspondence.register_incoming",
        actor=actor,
        entity=doc,
        new_values={
            "registry_number": registry,
            "external_reference": doc.external_reference,
            "letter_date": str(letter_date),
            "received_at": str(received_at),
            "department_id": getattr(routed_department, "pk", None),
        },
        source="erp",
    )
    return doc


@transaction.atomic
def route_correspondence(*, document: Document, department, actor) -> Document:
    if not _can_edit_documents(actor):
        raise DomainError("Yönləndirmə icazəniz yoxdur.")
    locked = Document.objects.select_for_update().get(pk=document.pk)
    if locked.direction != CorrespondenceDirection.INCOMING:
        raise DomainError("Yalnız daxil olan məktub yönləndirilə bilər.")
    locked.routed_department = department
    locked.correspondence_status = CorrespondenceStatus.ROUTED
    locked.updated_by = actor
    locked.save(
        update_fields=["routed_department", "correspondence_status", "updated_by", "updated_at"]
    )
    log_action(
        action="correspondence.route",
        actor=actor,
        entity=locked,
        new_values={"department_id": department.pk if department else None},
        source="erp",
    )
    return locked


@transaction.atomic
def prepare_outgoing_reply(
    *,
    incoming: Document,
    title: str,
    uploaded_file,
    actor,
) -> Document:
    if not _can_edit_documents(actor):
        raise DomainError("Cavab hazırlamaq icazəniz yoxdur.")
    locked_in = Document.objects.select_for_update().get(pk=incoming.pk)
    if locked_in.direction != CorrespondenceDirection.INCOMING:
        raise DomainError("Cavab yalnız daxil olan məktuba bağlanır.")
    _, outgoing_type = ensure_correspondence_types()
    today = timezone.localdate()
    registry = allocate_registry_number(
        direction=CorrespondenceDirection.OUTGOING, when=today
    )
    reply = DocumentService.upload_new(
        title=title,
        uploaded_file=uploaded_file,
        company=locked_in.company,
        lease=locked_in.lease,
        document_type=outgoing_type,
        created_by=actor,
        document_date=today,
        visible_to_resident=False,
    )
    reply.direction = CorrespondenceDirection.OUTGOING
    reply.registry_number = registry
    reply.received_at = today
    reply.published_at = today
    reply.related_correspondence = locked_in
    reply.party = locked_in.party
    reply.ticket = locked_in.ticket
    reply.work_order = locked_in.work_order
    reply.purchase_request = locked_in.purchase_request
    reply.purchase_order = locked_in.purchase_order
    reply.invoice = locked_in.invoice
    reply.routed_department = locked_in.routed_department
    reply.correspondence_status = CorrespondenceStatus.IN_PROGRESS
    reply.external_reference = locked_in.external_reference
    reply.save()
    if not locked_in.related_correspondence_id:
        locked_in.related_correspondence = reply
        locked_in.correspondence_status = CorrespondenceStatus.IN_PROGRESS
        locked_in.save(
            update_fields=["related_correspondence", "correspondence_status", "updated_at"]
        )
    log_action(
        action="correspondence.prepare_reply",
        actor=actor,
        entity=reply,
        new_values={
            "registry_number": registry,
            "in_reply_to": locked_in.registry_number,
        },
        source="erp",
    )
    return reply


def _approved_version_for(document: Document) -> DocumentVersion | None:
    """Latest Management-approved version still present on the document."""
    reqs = (
        ApprovalRequest.objects.filter(
            workflow_code=WF_DOCUMENT_APPROVE,
            status=ApprovalStatus.APPROVED,
            payload__document_id=document.pk,
        )
        .order_by("-decided_at", "-id")
    )
    for req in reqs:
        payload = req.payload or {}
        vid = payload.get("version_id")
        if not vid:
            continue
        ver = DocumentVersion.objects.filter(pk=vid, document=document).first()
        if ver:
            return ver
    return None


@transaction.atomic
def record_dispatch(
    *,
    document: Document,
    actor,
    recipient: str,
    channel: str = "manual",
    notes: str = "",
    operation_key: str | None = None,
    version: DocumentVersion | None = None,
) -> DocumentDispatch:
    """Record manual dispatch of the approved outgoing version (idempotent by operation_key)."""
    if not _can_edit_documents(actor):
        raise DomainError("Göndərmə qeydi icazəniz yoxdur.")
    locked = Document.objects.select_for_update().get(pk=document.pk)
    if locked.direction != CorrespondenceDirection.OUTGOING:
        raise DomainError("Yalnız gedən məktub göndərilə bilər.")
    recipient = (recipient or "").strip()
    if not recipient:
        raise DomainError("Alıcı tələb olunur.")
    ver = version or _approved_version_for(locked)
    if ver is None:
        raise DomainError("Göndərmə üçün Management təsdiqlənmiş versiya tələb olunur.")
    if ver.document_id != locked.pk:
        raise DomainError("Versiya bu sənədə aid deyil.")

    key = (operation_key or "").strip() or f"dispatch-{locked.pk}-{ver.pk}"
    existing = DocumentDispatch.objects.filter(document=locked, operation_key=key).first()
    if existing:
        return existing

    try:
        dispatch = DocumentDispatch.objects.create(
            document=locked,
            version=ver,
            recipient=recipient[:255],
            channel=(channel or "manual").strip()[:32] or "manual",
            dispatched_by=actor,
            dispatched_at=timezone.now(),
            notes=(notes or "").strip()[:255],
            operation_key=key,
        )
    except IntegrityError:
        return DocumentDispatch.objects.get(document=locked, operation_key=key)

    locked.correspondence_status = CorrespondenceStatus.DISPATCHED
    locked.updated_by = actor
    locked.save(update_fields=["correspondence_status", "updated_by", "updated_at"])
    log_action(
        action="correspondence.dispatch",
        actor=actor,
        entity=locked,
        new_values={
            "registry_number": locked.registry_number,
            "version_id": ver.pk,
            "version_label": ver.version_label,
            "recipient": dispatch.recipient,
            "channel": dispatch.channel,
            "dispatch_id": dispatch.pk,
        },
        source="erp",
    )
    return dispatch


def correspondence_queryset():
    return Document.objects.filter(direction__in=[
        CorrespondenceDirection.INCOMING,
        CorrespondenceDirection.OUTGOING,
    ]).select_related(
        "company",
        "lease",
        "document_type",
        "routed_department",
        "related_correspondence",
        "party",
    )


def filter_correspondence(
    qs,
    *,
    registry: str = "",
    external_ref: str = "",
    company_id: str = "",
    direction: str = "",
    date_from: str = "",
    date_to: str = "",
    date_field: str = "received",
    department_id: str = "",
    status: str = "",
):
    registry = (registry or "").strip()
    external_ref = (external_ref or "").strip()
    if registry:
        qs = qs.filter(registry_number__icontains=registry)
    if external_ref:
        qs = qs.filter(external_reference__icontains=external_ref)
    if company_id.isdigit():
        qs = qs.filter(company_id=int(company_id))
    if direction in (CorrespondenceDirection.INCOMING, CorrespondenceDirection.OUTGOING):
        qs = qs.filter(direction=direction)
    if department_id.isdigit():
        qs = qs.filter(routed_department_id=int(department_id))
    if status:
        qs = qs.filter(correspondence_status=status)
    field = "document_date" if date_field == "letter" else "received_at"
    if date_from:
        qs = qs.filter(**{f"{field}__gte": date_from})
    if date_to:
        qs = qs.filter(**{f"{field}__lte": date_to})
    return qs
