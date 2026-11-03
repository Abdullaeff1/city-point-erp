"""Document upload / versioning / replace / delete with audit + private storage."""

from __future__ import annotations

import hashlib

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit.services import log_action
from apps.core.services import Service
from apps.documents.models import Document, DocumentVersion
from apps.documents.validation import validate_document_file


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
        today = timezone.localdate()
        doc = Document(
            title=title.strip()[:200],
            document_type=document_type,
            company=company,
            space=space,
            lease=lease,
            parent_document=parent_document,
            published_at=document_date or today,
            document_date=document_date or today,
            visible_to_resident=visible_to_resident,
            version="1",
            size_label=f"{size // 1024} KB" if size else "",
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
        log_action(
            action="document.file_replaced",
            actor=created_by,
            entity=document,
            old_values={"file": old_meta},
            new_values={"file": _file_meta(document.file)},
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
            document.visible_to_resident = visible_to_resident
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
