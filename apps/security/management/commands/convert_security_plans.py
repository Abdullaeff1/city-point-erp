"""Convert pending security floor plan revisions to sanitized SVG."""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from apps.security.models import ConversionStatus
from apps.security.services import claim_pending_revisions, convert_revision


class Command(BaseCommand):
    help = "Convert pending SecurityFloorPlanRevision records (DXF/DWG → SVG)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="One batch then exit")
        parser.add_argument("--interval", type=int, default=30, help="Seconds between batches")
        parser.add_argument("--limit", type=int, default=5, help="Max revisions per batch")

    def handle(self, *args, **options):
        once = options["once"]
        interval = max(5, int(options["interval"] or 30))
        limit = max(1, int(options["limit"] or 5))
        while True:
            claimed = claim_pending_revisions(limit=limit)
            if not claimed:
                self.stdout.write("no pending revisions")
            for rev in claimed:
                status = convert_revision(rev)
                style = self.style.SUCCESS if status == ConversionStatus.READY else self.style.WARNING
                self.stdout.write(
                    style(
                        f"revision={rev.pk} plan={rev.plan_id} r{rev.revision_number} → {status}"
                    )
                )
            self.stdout.flush()
            if once:
                break
            time.sleep(interval)
