"""D08 — ticket + CRM paths into the central Document archive."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from io import StringIO

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.crm.models import Offer, OfferStatus, OfferVersion, Opportunity, OpportunityStatus
from apps.crm.services import CrmOfferService
from apps.documents.archive import archive_queryset_for, module_source
from apps.documents.crm_bridge import (
    document_for_offer,
    register_offer_version_pdf,
    share_offer_version_with_resident,
    version_for_offer_version,
)
from apps.documents.models import Document, DocumentSensitivity
from apps.documents.services import DocumentService
from apps.documents.ticket_bridge import link_legacy_ticket_attachment, register_ticket_attachment
from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyType
from apps.rbac.services import seed_rbac_catalog
from apps.residents.models import ResidentCompany
from apps.tickets.access import can_access_ticket_attachment
from apps.tickets.models import TicketDepartment, TicketStatus, TicketType
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import attach_ticket_file, create_ticket_from_portal

User = get_user_model()


def _pdf(name="a.pdf", body=b"%PDF-1.4 ticket"):
    return SimpleUploadedFile(name, body, content_type="application/pdf")


class TicketArchivePathTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        seed_ticket_taxonomy()
        cls.company_a = ResidentCompany.objects.create(
            name="D08A", slug="d08-a", portal_active=True
        )
        cls.company_b = ResidentCompany.objects.create(
            name="D08B", slug="d08-b", portal_active=True
        )
        cls.desk_dept = TicketDepartment.objects.get(code="servicedesk")
        cls.hvac = __import__(
            "apps.tickets.models", fromlist=["TicketSubcategory"]
        ).TicketSubcategory.objects.get(slug="hvac", is_active=True)

    def setUp(self):
        self.client = Client()
        self.mgmt = User.objects.create_user(
            username="d08-mgmt", email="d08-mgmt@test.az", password="x",
            role=Role.MANAGEMENT, is_staff=True,
        )
        self.desk = User.objects.create_user(
            username="d08-desk", email="d08-desk@test.az", password="x",
            role=Role.SERVICE_DESK, is_staff=True, ticket_department=self.desk_dept,
        )
        self.res_a = User.objects.create_user(
            username="d08-resa", email="d08-resa@test.az", password="x",
            role=Role.RESIDENT_USER, resident_company=self.company_a,
        )
        ensure_portal_membership(self.res_a, self.company_a)
        self.res_b = User.objects.create_user(
            username="d08-resb", email="d08-resb@test.az", password="x",
            role=Role.RESIDENT_USER, resident_company=self.company_b,
        )
        ensure_portal_membership(self.res_b, self.company_b)
        self.ticket = create_ticket_from_portal(
            company=self.company_a,
            requester=self.res_a,
            ticket_type=TicketType.INCIDENT,
            category=self.hvac.category,
            subcategory=self.hvac,
            description="D08 attach",
        )

    def test_resident_and_internal_attachments_archive_acl(self):
        resident_att, resident_doc = register_ticket_attachment(
            ticket=self.ticket,
            upload=_pdf("resident.pdf", b"%PDF-1.4 res"),
            actor=self.res_a,
            visible_to_resident=True,
        )
        internal_att = attach_ticket_file(
            self.ticket,
            actor=self.desk,
            upload=_pdf("internal.pdf", b"%PDF-1.4 int"),
            visible_to_resident=False,
        )
        self.assertTrue(resident_att.visible_to_resident)
        self.assertFalse(internal_att.visible_to_resident)
        self.assertEqual(resident_doc.ticket_id, self.ticket.pk)
        self.assertEqual(module_source(resident_doc), "ticket")
        self.assertEqual(module_source(internal_att.document), "ticket")

        # Management finds both by ticket code + company
        found = archive_queryset_for(
            self.mgmt,
            {"source": "ticket", "company": self.company_a.pk, "related": self.ticket.code},
        )
        self.assertEqual(found.count(), 2)

        # Resident A: portal-visible only
        self.assertTrue(
            can_access_ticket_attachment(
                self.res_a, self.ticket, attachment=resident_att
            )
        )
        self.assertFalse(
            can_access_ticket_attachment(
                self.res_a, self.ticket, attachment=internal_att
            )
        )
        # Company B denied both
        self.assertFalse(
            can_access_ticket_attachment(
                self.res_b, self.ticket, attachment=resident_att
            )
        )

        url_res = reverse("ticket_attachment_download", kwargs={"pk": resident_att.pk})
        url_int = reverse("ticket_attachment_download", kwargs={"pk": internal_att.pk})

        self.client.force_login(self.res_a)
        self.assertEqual(self.client.get(url_res).status_code, 200)
        self.assertEqual(self.client.get(url_int).status_code, 404)

        self.client.force_login(self.res_b)
        self.assertEqual(self.client.get(url_res).status_code, 404)
        self.assertEqual(self.client.get(url_int).status_code, 404)

        self.client.force_login(self.desk)
        self.assertEqual(self.client.get(url_int).status_code, 200)

        # Service desk cannot browse global archive (403 PermissionDenied or role home 302)
        self.assertEqual(archive_queryset_for(self.desk).count(), 0)
        self.client.force_login(self.desk)
        desk_archive = self.client.get(reverse("erp:documents"))
        self.assertIn(desk_archive.status_code, (302, 403))

    def test_legacy_backfill_idempotent(self):
        from apps.tickets.models import TicketAttachment

        legacy = TicketAttachment.objects.create(
            ticket=self.ticket,
            file=_pdf("legacy.pdf", b"%PDF-1.4 leg"),
            visible_to_resident=True,
        )
        doc1 = link_legacy_ticket_attachment(legacy)
        self.assertIsNotNone(doc1)
        legacy.refresh_from_db()
        self.assertEqual(legacy.document_id, doc1.pk)
        doc2 = link_legacy_ticket_attachment(legacy)
        self.assertEqual(doc1.pk, doc2.pk)
        self.assertEqual(
            Document.objects.filter(ticket=self.ticket, title__contains="legacy").count(),
            1,
        )

        out = StringIO()
        call_command("backfill_document_archive", stdout=out)
        self.assertIn("already_linked", out.getvalue())


class CrmOfferArchivePathTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.company = ResidentCompany.objects.create(
            name="D08 CRM Co", slug="d08-crm", portal_active=True
        )
        self.party = Party.objects.create(
            legal_name="D08 CRM Party",
            party_type=PartyType.ORGANIZATION,
            legacy_resident_company=self.company,
        )
        PartyRole.objects.get_or_create(party=self.party, role=PartyRoleCode.RESIDENT)
        self.sales = User.objects.create_user(
            username="d08-sales", email="d08-sales@test.az", password="x",
            role=Role.SALES, is_staff=True,
        )
        self.mgmt = User.objects.create_user(
            username="d08-crm-mgmt", email="d08-crm-mgmt@test.az", password="x",
            role=Role.MANAGEMENT, is_staff=True,
        )
        self.res = User.objects.create_user(
            username="d08-crm-res", email="d08-crm-res@test.az", password="x",
            role=Role.RESIDENT_USER, resident_company=self.company,
        )
        ensure_portal_membership(self.res, self.company)
        opp = Opportunity.objects.create(
            title="D08 Opp",
            party=self.party,
            status=OpportunityStatus.OPEN,
            created_by=self.sales,
        )
        self.offer = Offer.objects.create(
            opportunity=opp,
            party=self.party,
            status=OfferStatus.DRAFT,
        )
        self.v1 = OfferVersion.objects.create(
            offer=self.offer,
            version_number=1,
            rent_rate_per_m2=Decimal("33.00"),
            area_m2=Decimal("10.00"),
            created_by=self.sales,
        )
        self.offer.current_version = self.v1
        self.offer.save(update_fields=["current_version"])

    def test_offer_v1_shared_v2_draft_keeps_portal_pointer(self):
        CrmOfferService.generate_pdf(self.v1, actor=self.sales)
        self.v1.refresh_from_db()
        self.assertTrue(bool(self.v1.pdf_file))
        doc = document_for_offer(self.offer)
        self.assertIsNotNone(doc)
        self.assertEqual(module_source(doc), "crm")
        share_offer_version_with_resident(self.v1, actor=self.sales)
        doc.refresh_from_db()
        v1_arch = version_for_offer_version(doc, self.v1)
        self.assertEqual(doc.portal_shared_version_id, v1_arch.pk)
        shared_file = DocumentService.current_portal_file(doc)
        self.assertIsNotNone(shared_file)

        v2 = OfferVersion.objects.create(
            offer=self.offer,
            version_number=2,
            rent_rate_per_m2=Decimal("40.00"),
            area_m2=Decimal("10.00"),
            created_by=self.sales,
        )
        CrmOfferService.generate_pdf(v2, actor=self.sales)
        doc.refresh_from_db()
        # Draft v2 registered but portal still pinned to v1
        self.assertEqual(doc.portal_shared_version_id, v1_arch.pk)
        self.assertEqual(DocumentService.current_portal_file(doc).name, shared_file.name)
        self.assertIsNotNone(version_for_offer_version(doc, v2))

        found = archive_queryset_for(
            self.mgmt,
            {"source": "crm", "company": self.company.pk, "related": str(self.offer.pk)},
        )
        self.assertEqual(found.count(), 1)
        self.assertEqual(found.get().pk, doc.pk)

        # Idempotent re-register
        again = register_offer_version_pdf(self.v1, actor=self.sales)
        self.assertEqual(again.pk, doc.pk)
        self.assertEqual(
            doc.versions.filter(version_label="1").count(),
            1,
        )
