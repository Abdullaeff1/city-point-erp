"""Read-only inventory of upload surfaces before consolidating into the document archive (D08)."""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.documents.archive import (
    MODULE_SOURCES,
    SOURCE_OTHER,
    _source_q,
)
from apps.documents.models import Document


class Command(BaseCommand):
    help = "Print counts of legacy upload surfaces (TicketAttachment, Offer.pdf_file, Document by module)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Required. Only prints counts; nothing is written or moved.",
        )

    def handle(self, *args, **options):
        if not options.get("dry_run"):
            raise CommandError("Yalnız --dry-run dəstəklənir (heç nə dəyişdirilmir).")

        from apps.crm.models import OfferVersion
        from apps.documents.crm_bridge import document_for_offer, version_for_offer_version
        from apps.tickets.models import TicketAttachment

        ticket_attachments = TicketAttachment.objects.count()
        ticket_linked = TicketAttachment.objects.filter(document__isnull=False).count()
        ticket_unlinked = TicketAttachment.objects.filter(document__isnull=True).count()
        # The offer PDF lives on OfferVersion (one row per sent version of an Offer).
        with_pdf = OfferVersion.objects.exclude(Q(pdf_file="") | Q(pdf_file__isnull=True))
        offer_pdfs = with_pdf.count()
        offers_with_pdf = with_pdf.values("offer_id").distinct().count()
        offer_already = 0
        for ver in with_pdf.select_related("offer").iterator():
            doc = document_for_offer(ver.offer)
            if doc is not None and version_for_offer_version(doc, ver) is not None:
                offer_already += 1

        self.stdout.write("== Legacy upload surfaces ==")
        self.stdout.write(f"TicketAttachment: {ticket_attachments}")
        self.stdout.write(f"  linked_to_Document: {ticket_linked}")
        self.stdout.write(f"  unlinked (needs backfill): {ticket_unlinked}")
        self.stdout.write(f"Offer.pdf_file (OfferVersion rows): {offer_pdfs}")
        self.stdout.write(f"Offer.pdf_file (distinct offers): {offers_with_pdf}")
        self.stdout.write(f"  OfferVersion already in archive: {offer_already}")
        self.stdout.write(f"  OfferVersion needing backfill: {offer_pdfs - offer_already}")

        self.stdout.write("== Document by module source ==")
        total = Document.objects.count()
        self.stdout.write(f"Document total: {total}")
        for code, label in MODULE_SOURCES:
            pred = _source_q(code)
            n = Document.objects.filter(pred).count() if pred is not None else 0
            self.stdout.write(f"  {code}: {n}")

        self.stdout.write("== Module FK breakdown ==")
        for field in (
            "ticket",
            "offer",
            "work_order",
            "purchase_request",
            "purchase_order",
            "invoice",
            "lease",
            "party",
            "company",
            "space",
        ):
            n = Document.objects.filter(**{f"{field}__isnull": False}).count()
            self.stdout.write(f"  Document.{field}: {n}")

        unresolved = Document.objects.filter(_source_q(SOURCE_OTHER)).count()
        self.stdout.write(f"Unresolved (no module link, no company): {unresolved}")
        self.stdout.write("dry-run: no data modified.")
