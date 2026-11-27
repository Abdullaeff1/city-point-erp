"""Decision 05 — Accountant ↔ resident financial documents + payment evidence."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounting.models import JournalEntry
from apps.accounting.services import seed_minimal_coa
from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.billing.evidence_models import EvidenceStatus, InvoicePaymentEvidence
from apps.billing.evidence_services import (
    link_evidence_to_payment,
    notify_finance_of_evidence,
    resident_upload_payment_instruction,
    share_invoice_document,
    upload_official_invoice_document,
)
from apps.billing.models import Charge, ChargeSource, InvoiceStatus, Payment
from apps.billing.services import (
    confirm_invoice,
    generate_invoice_from_charges,
    invoice_balance,
    record_incoming_payment_verified,
    record_payment,
)
from apps.comms.models import Notification
from apps.core.services import DomainError
from apps.documents.models import Document
from apps.documents.services import DocumentService
from apps.parties.resolvers import party_for_company
from apps.residents.models import ResidentCompany
from apps.workflows.models import ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


def _pdf(name="proof.pdf", body=b"%PDF-1.4 proof"):
    return SimpleUploadedFile(name, body, content_type="application/pdf")


class EvidenceBase(TestCase):
    def setUp(self):
        seed_minimal_coa()
        self.company_a = ResidentCompany.objects.create(name="Ev A", slug="ev-a", portal_active=True)
        self.company_b = ResidentCompany.objects.create(name="Ev B", slug="ev-b", portal_active=True)
        self.party_a = party_for_company(self.company_a, ensure=True)
        self.party_b = party_for_company(self.company_b, ensure=True)
        self.res_a = User.objects.create_user(
            username="ev-res-a", email="ev-res-a@test.az", password="x", role=Role.RESIDENT_USER
        )
        self.res_b = User.objects.create_user(
            username="ev-res-b", email="ev-res-b@test.az", password="x", role=Role.RESIDENT_USER
        )
        ensure_portal_membership(self.res_a, self.company_a)
        ensure_portal_membership(self.res_b, self.company_b)
        self.accountant = User.objects.create_user(
            username="ev-acc", email="ev-acc@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        self.accountant2 = User.objects.create_user(
            username="ev-acc2", email="ev-acc2@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        self.manager = User.objects.create_user(
            username="ev-mgmt", email="ev-mgmt@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        self.invoice = self._issued(self.party_a, Decimal("1000.00"))
        self.invoice_b = self._issued(self.party_b, Decimal("300.00"))

    def _issued(self, party, amount):
        charge = Charge.objects.create(
            party=party,
            source=ChargeSource.RENT,
            description="rent",
            amount=amount,
            currency="AZN",
        )
        inv = generate_invoice_from_charges(party, [charge.pk], apply_vat=False)
        confirm_invoice(inv)
        inv.refresh_from_db()
        return inv


class OfficialInvoiceDocumentTests(EvidenceBase):
    def test_upload_does_not_share_until_explicit(self):
        doc = upload_official_invoice_document(self.invoice, _pdf("inv.pdf"), self.accountant)
        self.assertFalse(doc.visible_to_resident)
        self.assertIsNone(DocumentService.current_portal_file(doc))
        v1 = DocumentService.current_version(doc)
        share_invoice_document(doc, v1, self.accountant)
        doc.refresh_from_db()
        self.assertTrue(doc.visible_to_resident)
        self.assertEqual(doc.portal_shared_version_id, v1.pk)
        self.assertTrue(
            Notification.objects.filter(
                user=self.res_a, event_key=f"document.shared.{doc.pk}.v{v1.pk}"
            ).exists()
        )
        self.assertFalse(Notification.objects.filter(user=self.res_b).exists())

    def test_only_accountant_may_upload_or_share(self):
        with self.assertRaises(DomainError):
            upload_official_invoice_document(self.invoice, _pdf(), self.manager)
        doc = upload_official_invoice_document(self.invoice, _pdf(), self.accountant)
        with self.assertRaises(DomainError):
            share_invoice_document(doc, DocumentService.current_version(doc), self.manager)

    def test_portal_serves_shared_version_not_draft_replacement(self):
        doc = upload_official_invoice_document(
            self.invoice, _pdf("inv-v1.pdf", b"%PDF-1.4 SHARED-V1"), self.accountant, share=True
        )
        # Finance replaces with a draft v2 — not shared yet.
        upload_official_invoice_document(
            self.invoice, _pdf("inv-v2.pdf", b"%PDF-1.4 DRAFT-V2"), self.accountant
        )
        client = Client()
        client.force_login(self.res_a)
        resp = client.get(reverse("portal:invoice_official_download", args=[self.invoice.code]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"SHARED-V1", b"".join(resp.streaming_content))
        generic = client.get(reverse("portal:document_download", args=[doc.pk]))
        self.assertEqual(generic.status_code, 200)
        self.assertIn(b"SHARED-V1", b"".join(generic.streaming_content))

        doc.refresh_from_db()
        v2 = DocumentService.current_version(doc)
        share_invoice_document(doc, v2, self.accountant)
        resp2 = client.get(reverse("portal:invoice_official_download", args=[self.invoice.code]))
        self.assertIn(b"DRAFT-V2", b"".join(resp2.streaming_content))

    def test_other_company_cannot_download_official(self):
        upload_official_invoice_document(self.invoice, _pdf(), self.accountant, share=True)
        client = Client()
        client.force_login(self.res_b)
        resp = client.get(reverse("portal:invoice_official_download", args=[self.invoice.code]))
        self.assertEqual(resp.status_code, 404)


class PaymentEvidenceTests(EvidenceBase):
    def _finance_notes(self, evidence):
        return Notification.objects.filter(event_key=f"payment.evidence.{evidence.pk}")

    def test_balance_unchanged_after_evidence_then_600_after_verified_payment(self):
        je_before = JournalEntry.objects.count()
        ev = resident_upload_payment_instruction(
            self.invoice, _pdf("slip.pdf", b"%PDF-1.4 slip"), self.res_a, self.company_a
        )
        self.assertEqual(ev.status, EvidenceStatus.PENDING_REVIEW)
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 0)
        self.assertEqual(invoice_balance(self.invoice), Decimal("1000.00"))
        self.assertEqual(JournalEntry.objects.count(), je_before)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, InvoiceStatus.ISSUED)

        payment = record_incoming_payment_verified(
            invoice=self.invoice,
            amount=Decimal("400.00"),
            actor=self.accountant,
            reference="BANK-1",
            evidence=ev,
        )
        self.assertEqual(invoice_balance(self.invoice), Decimal("600.00"))
        ev.refresh_from_db()
        self.assertEqual(ev.status, EvidenceStatus.LINKED)
        self.assertEqual(ev.payment_id, payment.pk)
        self.assertEqual(ev.reviewed_by_id, self.accountant.pk)
        je_after = JournalEntry.objects.count()
        self.assertEqual(je_after, je_before + 1)

        # Replay for the same evidence is idempotent: no second Payment / JE.
        again = record_incoming_payment_verified(
            invoice=self.invoice,
            amount=Decimal("400.00"),
            actor=self.accountant,
            evidence=ev,
        )
        self.assertEqual(again.pk, payment.pk)
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 1)
        self.assertEqual(invoice_balance(self.invoice), Decimal("600.00"))
        self.assertEqual(JournalEntry.objects.count(), je_after)

    def test_verified_payment_requires_accountant(self):
        for actor in (self.manager, self.res_a):
            with self.assertRaises(DomainError):
                record_incoming_payment_verified(
                    invoice=self.invoice, amount=Decimal("10.00"), actor=actor
                )
        self.assertEqual(Payment.objects.count(), 0)

    def test_verified_payment_cannot_exceed_balance(self):
        with self.assertRaises(DomainError):
            record_incoming_payment_verified(
                invoice=self.invoice, amount=Decimal("1000.02"), actor=self.accountant
            )

    def test_cross_company_upload_blocked(self):
        with self.assertRaises(DomainError):
            resident_upload_payment_instruction(self.invoice, _pdf(), self.res_b, self.company_b)
        with self.assertRaises(DomainError):
            # Company B user claiming company A: not in portal scope.
            resident_upload_payment_instruction(self.invoice, _pdf(), self.res_b, self.company_a)
        with self.assertRaises(DomainError):
            # Company A user, own company, but invoice belongs to B.
            resident_upload_payment_instruction(self.invoice_b, _pdf(), self.res_a, self.company_a)
        # Staff cannot upload on behalf of a resident.
        with self.assertRaises(DomainError):
            resident_upload_payment_instruction(
                self.invoice, _pdf(), self.accountant, self.company_a
            )
        self.assertFalse(InvoicePaymentEvidence.objects.exists())

    def test_duplicate_evidence_notifies_once(self):
        ev1 = resident_upload_payment_instruction(
            self.invoice, _pdf("slip.pdf", b"%PDF-1.4 same"), self.res_a, self.company_a
        )
        ev2 = resident_upload_payment_instruction(
            self.invoice, _pdf("slip-again.pdf", b"%PDF-1.4 same"), self.res_a, self.company_a
        )
        self.assertEqual(ev1.pk, ev2.pk)
        self.assertEqual(InvoicePaymentEvidence.objects.count(), 1)
        notify_finance_of_evidence(ev1)
        notify_finance_of_evidence(ev1)
        notes = self._finance_notes(ev1)
        self.assertEqual(notes.filter(user=self.accountant).count(), 1)
        self.assertEqual(notes.filter(user=self.accountant2).count(), 1)
        self.assertEqual(notes.count(), 2)
        self.assertFalse(notes.filter(user=self.manager).exists())

    def test_link_evidence_to_existing_payment_creates_no_second_je(self):
        req = ApprovalService.request(
            workflow_code="finance.payment",
            requested_by=self.accountant,
            entity=self.invoice,
            payload={
                "invoice_id": self.invoice.pk,
                "invoice_code": self.invoice.code,
                "amount": "400.00",
                "method": "bank",
                "reference": "LEGACY",
            },
        )
        ApprovalService.decide(req, approved=True, decided_by=self.manager)
        req.refresh_from_db()
        payment = record_payment(
            invoice=self.invoice, amount=Decimal("400.00"), approval_request=req, method="bank"
        )
        ev = resident_upload_payment_instruction(
            self.invoice, _pdf("late.pdf", b"%PDF-1.4 late"), self.res_a, self.company_a
        )
        je_count = JournalEntry.objects.count()
        pay_count = Payment.objects.count()
        linked = link_evidence_to_payment(ev, payment, self.accountant)
        self.assertEqual(linked.status, EvidenceStatus.LINKED)
        self.assertEqual(linked.payment_id, payment.pk)
        self.assertEqual(JournalEntry.objects.count(), je_count)
        self.assertEqual(Payment.objects.count(), pay_count)
        self.assertEqual(invoice_balance(self.invoice), Decimal("600.00"))

    def test_link_requires_same_invoice(self):
        other = record_incoming_payment_verified(
            invoice=self.invoice_b, amount=Decimal("50.00"), actor=self.accountant
        )
        ev = resident_upload_payment_instruction(self.invoice, _pdf(), self.res_a, self.company_a)
        with self.assertRaises(DomainError):
            link_evidence_to_payment(ev, other, self.accountant)
        ev.refresh_from_db()
        self.assertEqual(ev.status, EvidenceStatus.PENDING_REVIEW)

    def test_legacy_pending_approval_cancelled_not_double_posted(self):
        legacy = ApprovalService.request(
            workflow_code="finance.payment",
            requested_by=self.accountant,
            entity=self.invoice,
            payload={
                "invoice_id": self.invoice.pk,
                "invoice_code": self.invoice.code,
                "amount": "400.00",
                "method": "bank",
                "reference": "LEG",
            },
        )
        record_incoming_payment_verified(
            invoice=self.invoice, amount=Decimal("400.00"), actor=self.accountant
        )
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, ApprovalStatus.CANCELLED)
        with self.assertRaises(Exception):
            ApprovalService.decide(legacy, approved=True, decided_by=self.manager)
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 1)

    def test_outgoing_record_payment_still_requires_approval(self):
        with self.assertRaises(DomainError):
            record_payment(
                invoice=self.invoice, amount=Decimal("10.00"), approval_request=None, method="bank"
            )


class PortalEvidenceViewTests(EvidenceBase):
    def test_portal_post_uploads_evidence_scoped_to_company(self):
        client = Client()
        client.force_login(self.res_a)
        url = reverse("portal:invoice_detail", args=[self.invoice.code])
        page = client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context["can_upload_payment_instruction"])
        resp = client.post(
            url,
            {"action": "upload_payment_instruction", "file": _pdf("slip.pdf", b"%PDF-1.4 view")},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(InvoicePaymentEvidence.objects.filter(company=self.company_a).count(), 1)
        self.assertEqual(invoice_balance(self.invoice), Decimal("1000.00"))

        # Company B resident cannot reach (or upload to) company A's invoice.
        other = Client()
        other.force_login(self.res_b)
        denied = other.post(
            url,
            {"action": "upload_payment_instruction", "file": _pdf("x.pdf", b"%PDF-1.4 x")},
        )
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(InvoicePaymentEvidence.objects.count(), 1)

    def test_finance_queue_and_record_payment_via_ui(self):
        ev = resident_upload_payment_instruction(
            self.invoice, _pdf("q.pdf", b"%PDF-1.4 q"), self.res_a, self.company_a
        )
        client = Client()
        client.force_login(self.accountant)
        queue = client.get(reverse("finance:payment_evidence"))
        self.assertEqual(queue.status_code, 200)
        self.assertContains(queue, "Yoxlama gözləyən ödəniş sənədləri")
        self.assertContains(queue, self.invoice.code)
        dl = client.get(reverse("finance:document_download", args=[ev.document_id]))
        self.assertEqual(dl.status_code, 200)
        resp = client.post(
            reverse("finance:payment_evidence"),
            {
                "action": "record_payment",
                "evidence_id": ev.pk,
                "amount": "400.00",
                "method": "bank",
                "reference": "UI-1",
            },
        )
        self.assertEqual(resp.status_code, 302)
        ev.refresh_from_db()
        self.assertEqual(ev.status, EvidenceStatus.LINKED)
        self.assertEqual(invoice_balance(self.invoice), Decimal("600.00"))
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 1)

    def test_management_cannot_record_via_queue(self):
        ev = resident_upload_payment_instruction(
            self.invoice, _pdf("m.pdf", b"%PDF-1.4 m"), self.res_a, self.company_a
        )
        client = Client()
        client.force_login(self.manager)
        client.post(
            reverse("finance:payment_evidence"),
            {"action": "record_payment", "evidence_id": ev.pk, "amount": "100.00"},
        )
        self.assertEqual(Payment.objects.count(), 0)
        ev.refresh_from_db()
        self.assertEqual(ev.status, EvidenceStatus.PENDING_REVIEW)
