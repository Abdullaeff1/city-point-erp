"""Copy legacy public media/documents files into PRIVATE_MEDIA_ROOT."""

from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.documents.models import Document, DocumentVersion


class Command(BaseCommand):
    help = "Move Document/DocumentVersion files from MEDIA_ROOT to PRIVATE_MEDIA_ROOT"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report what would be moved",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        media = Path(settings.MEDIA_ROOT)
        private = Path(settings.PRIVATE_MEDIA_ROOT)
        private.mkdir(parents=True, exist_ok=True)

        moved = 0
        missing = 0
        skipped = 0

        names = set()
        for doc in Document.objects.exclude(file="").exclude(file=None):
            if doc.file.name:
                names.add(doc.file.name)
        for ver in DocumentVersion.objects.exclude(file="").exclude(file=None):
            if ver.file.name:
                names.add(ver.file.name)

        for rel in sorted(names):
            src = media / rel
            dst = private / rel
            if dst.exists():
                skipped += 1
                continue
            if not src.exists():
                # Already only under private, or missing
                if (private / rel).exists():
                    skipped += 1
                else:
                    missing += 1
                    self.stdout.write(self.style.WARNING(f"missing: {rel}"))
                continue
            self.stdout.write(f"{'would move' if dry else 'move'}: {rel}")
            if not dry:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                # Keep public copy until ops confirm; optional delete left to deploy notes
            moved += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"done moved={moved} skipped={skipped} missing={missing} dry_run={dry}"
            )
        )
