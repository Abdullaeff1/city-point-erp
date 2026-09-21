"""Document upload / versioning (Phase 10 thin)."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.services import Service
from apps.documents.models import Document, DocumentVersion


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
    ) -> Document:
        cls.require(bool(title.strip()), "Başlıq tələb olunur.")
        cls.require(uploaded_file is not None, "Fayl tələb olunur.")
        size = getattr(uploaded_file, "size", 0) or 0
        doc = Document(
            title=title.strip()[:200],
            document_type=document_type,
            company=company,
            space=space,
            published_at=timezone.localdate(),
            version="1",
            size_label=f"{size // 1024} KB" if size else "",
            file_type=(getattr(uploaded_file, "name", "") or "").split(".")[-1].upper()[:16] or "FILE",
        )
        doc.file.save(getattr(uploaded_file, "name", "file.bin"), uploaded_file, save=True)
        DocumentVersion.objects.create(
            document=doc,
            version_label="1",
            file=doc.file,
            created_by=created_by,
            is_current=True,
        )
        return doc

    @classmethod
    @transaction.atomic
    def add_version(cls, document: Document, *, uploaded_file, created_by=None, label: str = "") -> DocumentVersion:
        DocumentVersion.objects.filter(document=document, is_current=True).update(is_current=False)
        n = document.versions.count() + 1
        ver_label = label or str(n)
        ver = DocumentVersion(
            document=document,
            version_label=ver_label,
            created_by=created_by,
            is_current=True,
        )
        ver.file.save(getattr(uploaded_file, "name", "file.bin"), uploaded_file, save=True)
        document.file = ver.file
        document.version = ver_label
        document.save(update_fields=["file", "version"])
        return ver
