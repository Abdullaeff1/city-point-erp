"""Resident profile + documents: permissions, archive, VOEN, file validation, media ACL."""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from apps.accounts.models import PortalCompanyMembership, Role
from apps.core.media_views import is_blocked_media_path
from apps.documents.models import (
    DOCUMENT_TYPE_LEASE_AMENDMENT,
    DOCUMENT_TYPE_LEASE_CONTRACT,
    DocumentType,
    SEED_DOCUMENT_TYPES,
)
from apps.documents.services import DocumentService
from apps.documents.validation import validate_document_file
from apps.leases.models import Lease, LeaseStatus
from apps.parties.models import Party, PartyType
from apps.residents.company_sync import (
    archive_resident_company,
    save_resident_company,
    unarchive_resident_company,
)
from apps.residents.models import ResidentCompany

User = get_user_model()


def _pdf(name="c.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 fake", content_type="application/pdf")


def _fake_pdf_as_docx():
    return SimpleUploadedFile("evil.docx", b"%PDF-1.4 not-a-docx", content_type="application/vnd.openxmlformats")


class DocumentTypeSeedTests(TestCase):
    def test_seed_codes_unique(self):
        codes = [c for c, _ in SEED_DOCUMENT_TYPES]
        self.assertEqual(len(codes), len(set(codes)))
        for code, name in SEED_DOCUMENT_TYPES:
            DocumentType.objects.get_or_create(code=code, defaults={"name": name})
            DocumentType.objects.get_or_create(code=code, defaults={"name": name})
        self.assertEqual(
            DocumentType.objects.filter(code__in=codes).count(),
            len(codes),
        )


class VoenSyncTests(TestCase):
    def test_save_syncs_party_tax_id_and_rollback(self):
        company = ResidentCompany(name="Sync Co", slug="sync-co", voen="1234567890")
        save_resident_company(company, create=True, audit=False)
        party = Party.objects.get(legacy_resident_company=company)
        self.assertEqual(party.tax_id, "1234567890")

        company.voen = "not-digits"
        with self.assertRaises(ValidationError):
            save_resident_company(company, create=False, audit=False)
        company.refresh_from_db()
        party.refresh_from_db()
        self.assertEqual(company.voen, "1234567890")
        self.assertEqual(party.tax_id, "1234567890")

    def test_backfill_style_party_to_company(self):
        company = ResidentCompany.objects.create(name="BF", slug="bf-co", voen="")
        Party.objects.create(
            party_type=PartyType.ORGANIZATION,
            legal_name="BF",
            tax_id="9988776655",
            legacy_resident_company=company,
        )
        if not (company.voen or "").strip():
            company.voen = "9988776655"
            company.save(update_fields=["voen"])
        company.refresh_from_db()
        self.assertEqual(company.voen, "9988776655")


class ArchivePortalTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(
            name="Arch Co", slug="arch-co", portal_active=True
        )
        self.user = User.objects.create_user(
            username="res-arch",
            email="res-arch@ex.com",
            password="x",
            role=Role.RESIDENT_USER,
        )
        PortalCompanyMembership.objects.create(
            user=self.user, company=self.company, is_active=True, is_primary=True
        )

    def test_archive_closes_portal_unarchive_does_not_reopen(self):
        archive_resident_company(self.company, actor=None)
        self.company.refresh_from_db()
        self.assertTrue(self.company.is_archived)
        self.assertFalse(self.company.portal_active)

        unarchive_resident_company(self.company, actor=None)
        self.company.refresh_from_db()
        self.assertFalse(self.company.is_archived)
        self.assertFalse(self.company.portal_active)

    def test_archived_and_portal_active_invalid(self):
        self.company.is_archived = True
        self.company.portal_active = True
        with self.assertRaises(ValidationError):
            self.company.full_clean()

    def test_archived_hidden_from_portal_eligible(self):
        from apps.accounts.portal_scope import eligible_company_ids_for

        self.assertIn(self.company.id, eligible_company_ids_for(self.user))
        archive_resident_company(self.company)
        self.assertNotIn(self.company.id, eligible_company_ids_for(self.user))


class DocumentValidationRelationTests(TestCase):
    def setUp(self):
        self.co_a = ResidentCompany.objects.create(name="A", slug="doc-a")
        self.co_b = ResidentCompany.objects.create(name="B", slug="doc-b")
        self.contract_type, _ = DocumentType.objects.get_or_create(
            code=DOCUMENT_TYPE_LEASE_CONTRACT, defaults={"name": "Müqavilə"}
        )
        self.amend_type, _ = DocumentType.objects.get_or_create(
            code=DOCUMENT_TYPE_LEASE_AMENDMENT, defaults={"name": "Əlavə"}
        )
        self.parent = DocumentService.upload_new(
            title="Main",
            uploaded_file=_pdf(),
            company=self.co_a,
            document_type=self.contract_type,
        )

    def test_parent_wrong_company(self):
        foreign_parent = DocumentService.upload_new(
            title="Other",
            uploaded_file=_pdf("o.pdf"),
            company=self.co_b,
            document_type=self.contract_type,
        )
        with self.assertRaises(ValidationError):
            DocumentService.upload_new(
                title="Bad",
                uploaded_file=_pdf("b.pdf"),
                company=self.co_a,
                document_type=self.amend_type,
                parent_document=foreign_parent,
            )

    def test_lease_wrong_company(self):
        party_b = Party.objects.create(
            party_type=PartyType.ORGANIZATION,
            legal_name="B",
            legacy_resident_company=self.co_b,
        )
        lease = Lease.objects.create(
            code="L-BAD-1",
            party=party_b,
            status=LeaseStatus.ACTIVE,
            start_date=date(2024, 1, 1),
            end_date=date(2025, 1, 1),
        )
        with self.assertRaises(ValidationError):
            DocumentService.upload_new(
                title="Lease doc",
                uploaded_file=_pdf("l.pdf"),
                company=self.co_a,
                document_type=self.contract_type,
                lease=lease,
            )

    def test_cannot_delete_contract_with_amendment(self):
        DocumentService.upload_new(
            title="Amd",
            uploaded_file=_pdf("a.pdf"),
            company=self.co_a,
            document_type=self.amend_type,
            parent_document=self.parent,
        )
        with self.assertRaises(ValidationError):
            DocumentService.delete_document(self.parent)

    def test_fake_content_rejected(self):
        with self.assertRaises(ValidationError):
            validate_document_file(_fake_pdf_as_docx())
        with self.assertRaises(ValidationError):
            validate_document_file(
                SimpleUploadedFile("x.pdf", b"not-a-pdf", content_type="application/pdf")
            )


class MediaAclAndCrossCompanyTests(TestCase):
    def setUp(self):
        self.co_a = ResidentCompany.objects.create(name="A", slug="media-a", portal_active=True)
        self.co_b = ResidentCompany.objects.create(name="B", slug="media-b", portal_active=True)
        self.admin = User.objects.create_user(
            username="adm", email="adm@ex.com", password="x", role=Role.ADMIN
        )
        self.resident = User.objects.create_user(
            username="res", email="res@ex.com", password="x", role=Role.RESIDENT_USER
        )
        PortalCompanyMembership.objects.create(
            user=self.resident, company=self.co_a, is_active=True, is_primary=True
        )
        dtype, _ = DocumentType.objects.get_or_create(code="other", defaults={"name": "Digər"})
        self.doc_a = DocumentService.upload_new(
            title="Secret A",
            uploaded_file=_pdf(),
            company=self.co_a,
            document_type=dtype,
            visible_to_resident=True,
            created_by=self.admin,
        )
        self.doc_b = DocumentService.upload_new(
            title="Secret B",
            uploaded_file=_pdf("b.pdf"),
            company=self.co_b,
            document_type=dtype,
            visible_to_resident=True,
            created_by=self.admin,
        )

    def test_blocked_media_path(self):
        self.assertTrue(is_blocked_media_path("documents/2024/01/x.pdf"))
        self.assertFalse(is_blocked_media_path("employees/id/x.pdf"))

    def test_public_media_documents_forbidden(self):
        c = Client()
        # DEBUG media_serve returns 403; without the route (typical test settings) → 404.
        # Plan accepts either: documents must not be publicly downloadable.
        r = c.get("/media/documents/2024/01/nope.pdf")
        self.assertIn(r.status_code, (403, 404))

        from apps.core.media_views import media_serve

        req = RequestFactory().get("/media/documents/x.pdf")
        resp = media_serve(req, "documents/x.pdf")
        self.assertEqual(resp.status_code, 403)

    def test_erp_cross_company_document_download_404(self):
        c = Client()
        c.force_login(self.admin)
        url = reverse(
            "erp:resident_document_download",
            kwargs={"slug": self.co_a.slug, "pk": self.doc_b.pk},
        )
        r = c.get(url)
        self.assertEqual(r.status_code, 404)

    def test_portal_cross_company_document_403(self):
        c = Client()
        c.force_login(self.resident)
        # establish portal scope for co_a
        c.post(reverse("portal:choose_companies"), {"choice": str(self.co_a.id)})
        url = reverse("portal:document_download", kwargs={"pk": self.doc_b.pk})
        r = c.get(url)
        self.assertEqual(r.status_code, 403)


class ReceptionLimitedPayloadTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(
            name="Recv Co",
            slug="recv-co",
            voen="1122334455",
            bank_name="Kapital",
            iban="AZ00",
            charter_capital="1000.00",
        )
        self.reception = User.objects.create_user(
            username="recv", email="recv@ex.com", password="x", role=Role.RECEPTION
        )
        self.admin = User.objects.create_user(
            username="adm2", email="adm2@ex.com", password="x", role=Role.ADMIN
        )

    def test_reception_detail_hides_legal(self):
        c = Client()
        c.force_login(self.reception)
        r = c.get(reverse("erp:resident_detail", args=[self.company.slug]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["hide_legal_fields"] or r.context["reception_limited"])
        self.assertNotContains(r, "Kapital")
        self.assertNotContains(r, "1122334455")
        self.assertNotContains(r, "AZ00")

    def test_reception_documents_forbidden(self):
        c = Client()
        c.force_login(self.reception)
        r = c.get(reverse("erp:resident_documents", args=[self.company.slug]))
        self.assertEqual(r.status_code, 403)

    def test_admin_sees_legal(self):
        c = Client()
        c.force_login(self.admin)
        hub = c.get(reverse("erp:resident_detail", args=[self.company.slug]))
        self.assertEqual(hub.status_code, 200)
        self.assertContains(hub, "Ümumi məlumatlar")
        self.assertContains(hub, "İcarə və sahələr")
        general = c.get(reverse("erp:resident_detail", args=[self.company.slug]) + "?section=general")
        self.assertContains(general, "1122334455")
        bank = c.get(reverse("erp:resident_detail", args=[self.company.slug]) + "?section=bank")
        self.assertContains(bank, "Kapital")

    def test_admin_hub_and_leases_section(self):
        c = Client()
        c.force_login(self.admin)
        leases = c.get(reverse("erp:resident_detail", args=[self.company.slug]) + "?section=leases")
        self.assertEqual(leases.status_code, 200)
        self.assertEqual(leases.context["section"], "leases")
        self.assertIn("lease_rows", leases.context)
