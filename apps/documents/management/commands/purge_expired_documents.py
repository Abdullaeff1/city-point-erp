"""Purge document files past DocumentType.retention_days (dry-run by default)."""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.documents.models import DEFAULT_RETENTION_DAYS, Document


class Command(BaseCommand):
    help = (
        "List or delete Document rows whose retention window has expired "
        "(based on document_type.retention_days or DEFAULT_RETENTION_DAYS)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete expired documents (default: dry-run list only).",
        )
        parser.add_argument("--limit", type=int, default=200)

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        limit = max(1, int(options["limit"]))
        today = timezone.localdate()
        expired_ids: list[int] = []

        qs = (
            Document.objects.select_related("document_type")
            .exclude(file="")
            .order_by("id")
        )
        for doc in qs.iterator(chunk_size=200):
            code = getattr(doc.document_type, "code", None) if doc.document_type_id else None
            days = None
            if doc.document_type_id:
                days = doc.document_type.retention_days
            if days is None and code:
                days = DEFAULT_RETENTION_DAYS.get(code)
            if not days:
                continue
            anchor = doc.document_date or doc.published_at
            if not anchor:
                continue
            if anchor + timedelta(days=int(days)) > today:
                continue
            expired_ids.append(doc.pk)
            if len(expired_ids) >= limit:
                break

        self.stdout.write(f"expired_candidates={len(expired_ids)} apply={apply}")
        if not expired_ids:
            return

        deleted = 0
        for pk in expired_ids:
            doc = Document.objects.filter(pk=pk).first()
            if not doc:
                continue
            if apply:
                try:
                    from apps.documents.services import DocumentService

                    DocumentService.delete_document(doc, actor=None)
                    deleted += 1
                except Exception as exc:  # noqa: BLE001
                    self.stderr.write(f"skip id={pk}: {exc}")
            else:
                self.stdout.write(
                    f"would_delete id={pk} title={doc.title!r} "
                    f"type={getattr(doc.document_type, 'code', '')} "
                    f"date={doc.document_date or doc.published_at}"
                )

        if apply:
            self.stdout.write(self.style.SUCCESS(f"deleted={deleted}"))
