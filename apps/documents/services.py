"""Document upload / versioning / replace / delete with audit + private storage."""

from __future__ import annotations

import hashlib

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit.services import log_action
from apps.core.services import Service
from apps.documents.access import sensitivity_for_new_document
from apps.documents.models import Document, DocumentVersion
from apps.documents.validation import validate_document_file

WF_DOCUMENT_APPROVE = "document.approve"


def _file_meta(uploaded_or_field) -> dict:
    name = getattr(uploaded_or_field, "name", "") or ""
    size = getattr(uploaded_or_field, "size", None)
    if size is None and hasattr(uploaded_or_field, "file"):
        try:
            size = uploaded_or_field.size
        except Exception:
            size = 0
    digest = ""
    try:
        if hasattr(uploaded_or_field, "open"):
            uploaded_or_field.open("rb")
        data = uploaded_or_field.read()
        if hasattr(uploaded_or_field, "seek"):
            uploaded_or_field.seek(0)
        digest = hashlib.sha256(data).hexdigest()[:16] if data else ""
    except Exception:
        digest = ""
    return {"name": name, "size": size or 0, "hash": digest}


class DocumentService(Service):
    @classmethod
    @transaction.atomic
    def upload_new(
        cls,
        *,
        title: str,
        uploaded_file,
        company=None,
        space=None,
        document_type=None,
        created_by=None,
        lease=None,
        parent_document=None,
        document_date=None,
        visible_to_resident: bool = False,
    ) -> Document:
        cls.require(bool(title.strip()), "Başlıq tələb olunur.")
        validate_document_file(uploaded_file)
        size = getattr(uploaded_file, "size", 0) or 0
        from apps.documents.access import clamp_portal_visibility

        today = timezone.localdate()
        content_type = getattr(uploaded_file, "content_type", "") or ""
        visible = clamp_portal_visibility(
            document_type=document_type, visible_to_resident=visible_to_resident
        )
        doc = Document(
            title=title.strip()[:200],
            document_type=document_type,
            company=company,
            space=space,
            lease=lease,
            parent_document=parent_document,
            published_at=document_date or today,
            document_date=document_date or today,
            visible_to_resident=visible,
            sensitivity=sensitivity_for_new_document(
                document_type=document_type, visible_to_resident=visible
            ),
            version="1",
            size_bytes=size or None,
            size_label=f"{size // 1024} KB" if size else "",
            content_type=content_type[:128],
            file_type=(getattr(uploaded_file, "name", "") or "").split(".")[-1].upper()[:16] or "FILE",
            created_by=created_by,
            updated_by=created_by,
        )
        doc.full_clean()
        doc.file.save(getattr(uploaded_file, "name", "file.bin"), uploaded_file, save=False)
        doc.save()
        DocumentVersion.objects.create(
            document=doc,
            version_label="1",
            file=doc.file,
            created_by=created_by,
            is_current=True,
        )
        log_action(
            action="document.created",
            actor=created_by,
            entity=doc,
            new_values={
                "title": doc.title,
                "company_id": doc.company_id,
                "file": _file_meta(doc.file),
            },
            source="erp",
        )
        return doc

    @classmethod
    @transaction.atomic
    def add_version(cls, document: Document, *, uploaded_file, created_by=None, label: str = "") -> DocumentVersion:
        validate_document_file(uploaded_file)
        old_meta = _file_meta(document.file) if document.file else {}
        old_name = document.file.name if document.file else ""
        old_storage = document.file.storage if document.file else None

        DocumentVersion.objects.filter(document=document, is_current=True).update(is_current=False)
        n = document.versions.count() + 1
        ver_label = label or str(n)
        ver = DocumentVersion(
            document=document,
            version_label=ver_label,
            created_by=created_by,
            is_current=True,
        )
        ver.file.save(getattr(uploaded_file, "name", "file.bin"), uploaded_file, save=False)
        ver.save()
        document.file = ver.file
        document.version = ver_label
        document.updated_by = created_by
        size = getattr(uploaded_file, "size", 0) or 0
        document.size_label = f"{size // 1024} KB" if size else document.size_label
        document.file_type = (getattr(uploaded_file, "name", "") or "").split(".")[-1].upper()[:16] or document.file_type
        document.save(update_fields=["file", "version", "updated_by", "size_label", "file_type", "updated_at"])
        # Policy: new version supersedes any pending Management review of older content.
        cls.cancel_pending_approvals(
            document,
            actor=created_by,
            comment=_("Yeni versiya yükləndi — əvvəlki təsdiq sorğusu ləğv edildi."),
        )
        log_action(
            action="document.file_replaced",
            actor=created_by,
            entity=document,
            old_values={"file": old_meta},
            new_values={"file": _file_meta(document.file), "version": ver_label},
            source="erp",
        )

        def _cleanup():
            if old_name and old_storage and old_name != document.file.name:
                try:
                    old_storage.delete(old_name)
                except Exception:
                    pass

        transaction.on_commit(_cleanup)
        return ver

    @classmethod
    @transaction.atomic
    def update_meta(
        cls,
        document: Document,
        *,
        title=None,
        document_type=None,
        document_date=None,
        visible_to_resident=None,
        lease=None,
        parent_document=None,
        actor=None,
    ) -> Document:
        if title is not None:
            document.title = title.strip()[:200]
        if document_type is not None:
            document.document_type = document_type
        if document_date is not None:
            document.document_date = document_date
            document.published_at = document_date
        if visible_to_resident is not None:
            from apps.documents.access import clamp_portal_visibility, sensitivity_for_new_document

            dtype = document_type if document_type is not None else document.document_type
            visible = clamp_portal_visibility(
                document_type=dtype, visible_to_resident=visible_to_resident
            )
            document.visible_to_resident = visible
            document.sensitivity = sensitivity_for_new_document(
                document_type=dtype, visible_to_resident=visible
            )
        if lease is not None:
            document.lease = lease
        if parent_document is not None:
            document.parent_document = parent_document
        document.updated_by = actor
        document.full_clean()
        document.save()
        log_action(
            action="document.updated",
            actor=actor,
            entity=document,
            new_values={"title": document.title, "visible_to_resident": document.visible_to_resident},
            source="erp",
        )
        return document

    @classmethod
    @transaction.atomic
    def delete_document(cls, document: Document, *, actor=None) -> None:
        if document.amendments.exists():
            raise ValidationError(_("Əlavəsi olan müqavilə silinə bilməz."))
        meta = _file_meta(document.file) if document.file else {}
        log_action(
            action="document.deleted",
            actor=actor,
            entity=document,
            old_values={"title": document.title, "file": meta},
            source="erp",
        )
        # Model.delete audits storage cleanup after DB commit
        document.delete()

    @classmethod
    def current_version(cls, document: Document) -> DocumentVersion | None:
        return (
            document.versions.filter(is_current=True).order_by("-created_at").first()
            or document.versions.order_by("-created_at").first()
        )

    @classmethod
    def pending_approval_for_document(cls, document: Document):
        from apps.workflows.models import ApprovalRequest, ApprovalStatus

        return (
            ApprovalRequest.objects.filter(
                workflow_code=WF_DOCUMENT_APPROVE,
                status=ApprovalStatus.PENDING,
                payload__document_id=document.pk,
            )
            .order_by("-created_at")
            .first()
        )

    @classmethod
    def latest_decision_for_document(cls, document: Document):
        from apps.workflows.models import ApprovalRequest, ApprovalStatus

        return (
            ApprovalRequest.objects.filter(
                workflow_code=WF_DOCUMENT_APPROVE,
                payload__document_id=document.pk,
            )
            .exclude(status=ApprovalStatus.CANCELLED)
            .order_by("-decided_at", "-created_at")
            .first()
        )

    @classmethod
    @transaction.atomic
    def cancel_pending_approvals(cls, document: Document, *, actor=None, comment: str = "") -> int:
        from apps.workflows.models import ApprovalRequest, ApprovalStatus
        from apps.workflows.services import ApprovalService

        pending = list(
            ApprovalRequest.objects.select_for_update().filter(
                workflow_code=WF_DOCUMENT_APPROVE,
                status=ApprovalStatus.PENDING,
                payload__document_id=document.pk,
            )
        )
        for req in pending:
            ApprovalService.cancel(req, actor=actor, comment=comment)
        return len(pending)

    @classmethod
    @transaction.atomic
    def submit_for_approval(cls, document: Document, *, actor) -> "ApprovalRequest":
        """Submit the current DocumentVersion for Management approval.

        Decision ownership: ApprovalRequest (entity=DocumentVersion).
        Business outcome remains on the Document + version history.
        """
        from apps.rbac.services import user_has_permission
        from apps.workflows.services import ApprovalService

        cls.require(actor is not None, "İstifadəçi tələb olunur.")
        cls.require(
            user_has_permission(actor, "document.edit"),
            "Sənəd təsdiqinə göndərmək üçün icazəniz yoxdur.",
        )
        dtype = document.document_type
        cls.require(
            dtype is not None and bool(dtype.requires_approval),
            "Bu sənəd tipi Management təsdiqi tələb etmir.",
        )
        version = cls.current_version(document)
        cls.require(version is not None and bool(version.file), "Təsdiq üçün versiya faylı yoxdur.")

        existing = cls.pending_approval_for_document(document)
        if existing is not None:
            payload = existing.payload or {}
            if (
                payload.get("version_id") == version.pk
                and existing.entity_id == version.pk
            ):
                # Idempotent re-submit of the same pending version.
                return existing
            raise ValidationError(
                _("Bu sənəd üçün artıq gözləyən təsdiq var. Yeni versiya yükləyin və ya qərarı gözləyin.")
            )

        req = ApprovalService.request(
            workflow_code=WF_DOCUMENT_APPROVE,
            requested_by=actor,
            entity=version,
            payload={
                "document_id": document.pk,
                "document_title": document.title[:200],
                "version_id": version.pk,
                "version_label": version.version_label,
                "company_id": document.company_id,
                "document_type": getattr(dtype, "code", "") or "",
                "department": getattr(actor, "role", "") or "",
            },
        )
        log_action(
            action="document.approval_requested",
            actor=actor,
            entity=document,
            new_values={
                "approval_id": req.pk,
                "version_id": version.pk,
                "version_label": version.version_label,
            },
            source="erp",
        )
        return req

    @classmethod
    @transaction.atomic
    def decide_approval(
        cls,
        request: "ApprovalRequest",
        *,
        actor,
        approved: bool,
        comment: str = "",
    ) -> "ApprovalRequest":
        """Apply Management decision; ApprovalRequest owns the decision identity."""
        from apps.management.access import can_decide_approvals
        from apps.workflows.models import ApprovalRequest, ApprovalStatus
        from apps.workflows.services import ApprovalService

        cls.require(can_decide_approvals(actor), "Təsdiq qərarı vermək icazəniz yoxdur.")
        locked = ApprovalRequest.objects.select_for_update().get(pk=request.pk)
        cls.require(
            locked.workflow_code == WF_DOCUMENT_APPROVE,
            "Sənəd təsdiqi deyil.",
        )
        cls.require(
            locked.status == ApprovalStatus.PENDING,
            "Yalnız gözləyən sorğu qərar verilə bilər.",
        )
        version = locked.entity
        if version is None:
            version_id = (locked.payload or {}).get("version_id")
            version = DocumentVersion.objects.filter(pk=version_id).first()
        cls.require(version is not None, "Baxılan sənəd versiyası tapılmadı.")

        decided = ApprovalService.decide(
            locked, approved=approved, decided_by=actor, comment=comment
        )
        document = version.document
        # Keep correspondence registry status in sync when present.
        if getattr(document, "direction", None):
            from apps.documents.models import CorrespondenceStatus

            if approved:
                document.correspondence_status = CorrespondenceStatus.APPROVED
            else:
                document.correspondence_status = CorrespondenceStatus.IN_PROGRESS
            document.save(update_fields=["correspondence_status", "updated_at"])
        log_action(
            action="document.approval_decided",
            actor=actor,
            entity=document,
            new_values={
                "approval_id": decided.pk,
                "status": decided.status,
                "version_id": version.pk,
                "version_label": version.version_label,
                "comment": (comment or "")[:200],
            },
            source="erp",
        )
        return decided

    @classmethod
    def approval_summary_for_document(cls, document: Document) -> dict:
        pending = cls.pending_approval_for_document(document)
        if pending is not None:
            payload = pending.payload or {}
            return {
                "status": "pending",
                "approval_id": pending.pk,
                "version_label": payload.get("version_label") or "",
                "version_id": payload.get("version_id"),
                "decided_at": None,
                "comment": "",
                "requested_by": pending.requested_by,
            }
        latest = cls.latest_decision_for_document(document)
        if latest is None:
            return {
                "status": "",
                "approval_id": None,
                "version_label": document.version or "",
                "version_id": None,
                "decided_at": None,
                "comment": "",
                "requested_by": None,
            }
        payload = latest.payload or {}
        return {
            "status": latest.status,
            "approval_id": latest.pk,
            "version_label": payload.get("version_label") or "",
            "version_id": payload.get("version_id"),
            "decided_at": latest.decided_at,
            "comment": latest.comment or "",
            "requested_by": latest.requested_by,
            "decided_by": latest.decided_by,
        }
