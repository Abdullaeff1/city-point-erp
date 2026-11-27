"""Decision 08 — private archive filters + explicit portal share versions."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounting.services import seed_minimal_coa
from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.billing.evidence_services import upload_official_invoice_document
from apps.billing.models import Charge, ChargeSource
from apps.billing.services import confirm_invoice, generate_invoice_from_charges
from apps.comms.models import Notification
from apps.core.services import DomainError
from apps.documents.access import user_can_download_document
from apps.documents.archive import (
    ARCHIVE_PAGE_SIZE,
    archive_queryset_for,
    module_source,
)
from apps.documents.models import Document, DocumentSensitivity
from apps.documents.services import DocumentService
from apps.parties.resolvers import party_for_company
from apps.residents.models import ResidentCompany

User = get_user_model()


def _pdf(name="a.pdf", body=b"%PDF-1.4 a"):
    return SimpleUploadedFile(name, body, content_type="application/pdf")


class ArchiveBase(TestCase):
    def setUp(self):
        seed_minimal_coa()
        self.company = ResidentCompany.objects.create(name="Arc A", slug="arc-a", portal_active=True)
        self.other_company = ResidentCompany.objects.create(
            name="Arc B", slug="arc-b", portal_active=True
        )
        self.party = party_for_company(self.company, ensure=True)
        self.accountant = User.objects.create_user(
            username="arc-acc", email="arc-acc@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        self.manager = User.objects.create_user(
            username="arc-mgmt", email="arc-mgmt@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        self.admin = User.objects.create_user(
            username="arc-admin", email="arc-admin@test.az", password="x", role=Role.ADMIN, is_staff=True
        )
        self.service_desk = User.objects.create_user(
            username="arc-sd", email="arc-sd@test.az", password="x", role=Role.SERVICE_DESK, is_staff=True
        )
        self.reception = User.objects.create_user(
            username="arc-rec", email="arc-rec@test.az", password="x", role=Role.RECEPTION, is_staff=True
        )
        self.res = User.objects.create_user(
            username="arc-res", email="arc-res@test.az", password="x", role=Role.RESIDENT_USER
        )
        self.res_other = User.objects.create_user(
            username="arc-res-b", email="arc-res-b@test.az", password="x", role=Role.RESIDENT_USER
        )
        ensure_portal_membership(self.res, self.company)
        ensure_portal_membership(self.res_other, self.other_company)
        charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="rent",
            amount=Decimal("100.00"),
            currency="AZN",
        )
        self.invoice = generate_invoice_from_charges(self.party, [charge.pk], apply_vat=False)
        confirm_invoice(self.invoice)


class ArchiveFilterTests(ArchiveBase):
    def test_management_filters_find_finance_uploaded_document(self):
        doc = upload_official_invoice_document(self.invoice, _pdf("inv.pdf"), self.accountant)
        generic = DocumentService.upload_new(
            title="Ümumi qeyd",
            uploaded_file=_pdf("g.pdf", b"%PDF-1.4 g"),
            company=self.other_company,
            created_by=self.manager,
        )
        self.assertEqual(module_source(doc), "finance")
        self.assertEqual(module_source(generic), "resident")

        filters = {
            "source": "finance",
            "company": self.company.pk,
            "related": self.invoice.code,
            "type": "invoice_official",
            "uploader": self.accountant.pk,
            "visibility": "internal",
            "q": "Rəsmi",
            "supplier": str(self.party.pk),
        }
        qs = archive_queryset_for(self.manager, filters)
        self.assertEqual(list(qs), [doc])
        self.assertEqual(list(archive_queryset_for(self.admin, {"source": "resident"})), [generic])
        self.assertEqual(
            list(archive_queryset_for(self.manager, {"visibility": "portal"})), []
        )

        client = Client()
        client.force_login(self.manager)
        resp = client.get(
            reverse("erp:documents"),
            {"source": "finance", "related": self.invoice.code, "company": self.company.pk},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([d.pk for d in resp.context["documents"]], [doc.pk])
        self.assertEqual(resp.context["authorized_count"], 1)
        self.assertContains(resp, "Kargüzarlıq reyestri")

    def test_date_filters_and_stable_order(self):
        old = DocumentService.upload_new(
            title="Köhnə",
            uploaded_file=_pdf("o.pdf", b"%PDF-1.4 o"),
            company=self.company,
            created_by=self.manager,
            document_date=date(2026, 1, 5),
        )
        new = DocumentService.upload_new(
            title="Yeni",
            uploaded_file=_pdf("n.pdf", b"%PDF-1.4 n"),
            company=self.company,
            created_by=self.manager,
            document_date=timezone.localdate(),
        )
        qs = archive_queryset_for(self.manager, {})
        self.assertEqual([d.pk for d in qs], [new.pk, old.pk])
        only_old = archive_queryset_for(
            self.manager, {"date_from": date(2026, 1, 1), "date_to": date(2026, 1, 31)}
        )
        self.assertEqual(list(only_old), [old])
        recent = archive_queryset_for(
            self.manager, {"date_from": timezone.localdate() - timedelta(days=1)}
        )
        self.assertEqual(list(recent), [new])

    def test_non_management_gets_empty_queryset_and_403(self):
        upload_official_invoice_document(self.invoice, _pdf(), self.accountant)
        for user in (self.accountant, self.service_desk, self.reception, self.res):
            self.assertEqual(archive_queryset_for(user, {}).count(), 0)
        client = Client()
        client.force_login(self.service_desk)
        # PermissionDenied → SoftPermissionDeniedMiddleware: redirect, no archive body.
        resp = client.get(reverse("erp:documents"))
        self.assertEqual(resp.status_code, 302)

    def test_pagination_is_50(self):
        for i in range(ARCHIVE_PAGE_SIZE + 3):
            DocumentService.upload_new(
                title=f"Doc {i}",
                uploaded_file=_pdf(f"d{i}.pdf", b"%PDF-1.4 d"),
                company=self.company,
                created_by=self.manager,
            )
        client = Client()
        client.force_login(self.manager)
        page1 = client.get(reverse("erp:documents"))
        self.assertEqual(len(page1.context["documents"]), ARCHIVE_PAGE_SIZE)
        self.assertEqual(page1.context["authorized_count"], ARCHIVE_PAGE_SIZE + 3)
        page2 = client.get(reverse("erp:documents"), {"page": 2})
        self.assertEqual(len(page2.context["documents"]), 3)


class FinanceDocumentAccessTests(ArchiveBase):
    def test_accountant_downloads_finance_document_others_denied(self):
        doc = upload_official_invoice_document(self.invoice, _pdf("inv.pdf"), self.accountant)
        self.assertTrue(user_can_download_document(self.accountant, doc))
        self.assertTrue(user_can_download_document(self.manager, doc))
        self.assertFalse(user_can_download_document(self.reception, doc))
        self.assertFalse(user_can_download_document(self.res, doc))
        self.assertFalse(user_can_download_document(self.res_other, doc))

        client = Client()
        client.force_login(self.accountant)
        self.assertEqual(
            client.get(reverse("finance:document_download", args=[doc.pk])).status_code, 200
        )
        denied = Client()
        denied.force_login(self.reception)
        self.assertNotEqual(
            denied.get(reverse("finance:document_download", args=[doc.pk])).status_code, 200
        )

    def test_shared_document_only_for_its_company(self):
        doc = upload_official_invoice_document(
            self.invoice, _pdf("inv.pdf"), self.accountant, share=True
        )
        doc.refresh_from_db()
        self.assertEqual(doc.sensitivity, DocumentSensitivity.PUBLIC_RESIDENT)
        own = Client()
        own.force_login(self.res)
        self.assertEqual(own.get(reverse("portal:document_download", args=[doc.pk])).status_code, 200)
        other = Client()
        other.force_login(self.res_other)
        self.assertEqual(
            other.get(reverse("portal:document_download", args=[doc.pk])).status_code, 302
        )


class ShareVersionTests(ArchiveBase):
    def test_share_v1_then_v2(self):
        doc = DocumentService.upload_new(
            title="Hesab",
            uploaded_file=_pdf("v1.pdf", b"%PDF-1.4 V1"),
            company=self.company,
            created_by=self.accountant,
        )
        v1 = DocumentService.current_version(doc)
        self.assertIsNone(DocumentService.current_portal_file(doc))

        DocumentService.share_version_with_resident(
            doc, v1, actor=self.accountant, company=self.company
        )
        doc.refresh_from_db()
        self.assertEqual(doc.portal_shared_version_id, v1.pk)
        self.assertTrue(DocumentService.current_portal_file(doc).name.endswith(".pdf"))
        key1 = f"document.shared.{doc.pk}.v{v1.pk}"
        self.assertEqual(Notification.objects.filter(event_key=key1).count(), 1)

        # Re-share v1 → no duplicate notification.
        DocumentService.share_version_with_resident(
            doc, v1, actor=self.accountant, company=self.company
        )
        self.assertEqual(Notification.objects.filter(event_key=key1).count(), 1)

        # Draft v2 does not auto-promote.
        v2 = DocumentService.add_version(
            doc, uploaded_file=_pdf("v2.pdf", b"%PDF-1.4 V2"), created_by=self.accountant
        )
        doc.refresh_from_db()
        self.assertEqual(doc.portal_shared_version_id, v1.pk)
        with DocumentService.current_portal_file(doc).open("rb") as fh:
            self.assertIn(b"V1", fh.read())

        DocumentService.share_version_with_resident(
            doc, v2, actor=self.accountant, company=self.company
        )
        doc.refresh_from_db()
        self.assertEqual(doc.portal_shared_version_id, v2.pk)
        with DocumentService.current_portal_file(doc).open("rb") as fh:
            self.assertIn(b"V2", fh.read())
        key2 = f"document.shared.{doc.pk}.v{v2.pk}"
        self.assertEqual(Notification.objects.filter(event_key=key2, user=self.res).count(), 1)
        self.assertFalse(Notification.objects.filter(user=self.res_other).exists())

    def test_company_must_match(self):
        doc = DocumentService.upload_new(
            title="Hesab",
            uploaded_file=_pdf(),
            company=self.company,
            created_by=self.accountant,
        )
        v1 = DocumentService.current_version(doc)
        with self.assertRaises(DomainError):
            DocumentService.share_version_with_resident(
                doc, v1, actor=self.accountant, company=self.other_company
            )
        doc.refresh_from_db()
        self.assertFalse(doc.visible_to_resident)
        self.assertIsNone(doc.portal_shared_version_id)

    def test_version_must_belong_to_document(self):
        doc = DocumentService.upload_new(
            title="A", uploaded_file=_pdf(), company=self.company, created_by=self.accountant
        )
        other = DocumentService.upload_new(
            title="B",
            uploaded_file=_pdf("b.pdf", b"%PDF-1.4 b"),
            company=self.company,
            created_by=self.accountant,
        )
        with self.assertRaises(DomainError):
            DocumentService.share_version_with_resident(
                doc,
                DocumentService.current_version(other),
                actor=self.accountant,
                company=self.company,
            )

    def test_ensure_type_is_idempotent(self):
        a = DocumentService.ensure_type("custom_t", "Xüsusi")
        b = DocumentService.ensure_type("custom_t", "Başqa ad")
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(b.name, "Xüsusi")
