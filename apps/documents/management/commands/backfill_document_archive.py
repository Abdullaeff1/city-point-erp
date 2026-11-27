"""Idempotent historical linking of TicketAttachment / OfferVersion PDF into Document archive.

Default is ``--dry-run`` (counts only). ``--apply`` writes Document rows and links;
never deletes source files or changes production storage layout beyond private Document copies.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q


class Command(BaseCommand):
    help = "Dry-run / apply backfill of ticket + CRM offer files into the Document archive (D08)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help="Report only (default).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Create missing Document links (idempotent).",
        )

    def handle(self, *args, **options):
        apply = bool(options.get("apply"))
        dry_run = not apply

        from apps.crm.models import OfferVersion
        from apps.documents.crm_bridge import register_offer_version_pdf
        from apps.documents.ticket_bridge import link_legacy_ticket_attachment
        from apps.tickets.models import TicketAttachment

        self.stdout.write("== TicketAttachment ==")
        tickets = TicketAttachment.objects.select_related("ticket", "document").order_by("id")
        t_linked = t_already = t_missing = t_ambiguous = 0
        for att in tickets.iterator():
            if att.document_id:
                t_already += 1
                continue
            if not att.file:
                t_missing += 1
                continue
            if dry_run:
                t_linked += 1  # would link
                continue
            doc = link_legacy_ticket_attachment(att)
            if doc is None:
                t_missing += 1
            else:
                t_linked += 1

        self.stdout.write(
            f"  already_linked={t_already} would_or_linked={t_linked} "
            f"missing_file={t_missing} ambiguous={t_ambiguous}"
        )

        self.stdout.write("== OfferVersion.pdf_file ==")
        with_pdf = OfferVersion.objects.exclude(Q(pdf_file="") | Q(pdf_file__isnull=True)).select_related(
            "offer", "offer__party"
        )
        o_linked = o_already = o_missing = 0
        from apps.documents.crm_bridge import document_for_offer, version_for_offer_version

        for ver in with_pdf.iterator():
            doc = document_for_offer(ver.offer)
            if doc is not None and version_for_offer_version(doc, ver) is not None:
                o_already += 1
                continue
            if dry_run:
                o_linked += 1
                continue
            result = register_offer_version_pdf(ver)
            if result is None:
                o_missing += 1
            else:
                o_linked += 1

        self.stdout.write(
            f"  already_linked={o_already} would_or_linked={o_linked} missing_or_unreadable={o_missing}"
        )
        mode = "APPLY" if apply else "DRY-RUN"
        self.stdout.write(f"{mode} complete. Source TicketAttachment / OfferVersion.pdf_file rows preserved.")
