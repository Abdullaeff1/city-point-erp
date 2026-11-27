"""Decision 04 — outgoing Management approval context + incoming Finance verification."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounting.services import seed_minimal_coa
from apps.accounts.models import Role
from apps.billing.models import Charge, ChargeSource
from apps.billing.services import (
    confirm_invoice,
    generate_invoice_from_charges,
    invoice_balance,
    record_incoming_payment_verified,
)
from apps.finance.ap_services import SupplierInvoiceService, WF_SUPPLIER_PAYMENT
from apps.parties.models import Party, PartyType
from apps.parties.resolvers import party_for_company
from apps.procurement.models import POLine, POStatus, PurchaseOrder
from apps.rbac.services import seed_rbac_catalog
from apps.residents.models import ResidentCompany
from apps.workflows.models import ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


class Decision04PaymentAuthorityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def setUp(self):
        seed_minimal_coa()
        self.mgmt = User.objects.create_user(
            username="d04-mgmt",
            email="d04-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.acct = User.objects.create_user(
            username="d04-acct",
            email="d04-acct@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.supplier = Party.objects.create(
            legal_name="D04 Supplier", party_type=PartyType.ORGANIZATION
        )
        self.po = PurchaseOrder.objects.create(
            code="PO-D04-1", supplier_party=self.supplier, status=POStatus.SENT
        )
        self.line = POLine.objects.create(
            po=self.po,
            description="Goods",
            qty=Decimal("10"),
            unit_price=Decimal("100.00"),
            received_qty=Decimal("10"),
        )
        self.client = Client()

    def _recognized_1000(self):
        inv = SupplierInvoiceService.create_draft(
            supplier_party=self.supplier,
            supplier_invoice_no="D04-1000",
            lines=[
                {
                    "po_line": self.line,
                    "qty_invoiced": Decimal("10"),
                    "unit_price": Decimal("100.00"),
                }
            ],
            actor=self.acct,
        )
        matched = SupplierInvoiceService.validate_and_match_or_hold(inv, actor=self.acct)
        return SupplierInvoiceService.recognize_payable(matched, actor=self.acct)

    def test_ap_azn1_approval_context_and_no_settle(self):
        inv = self._recognized_1000()
        req = SupplierInvoiceService.request_supplier_payment(
            inv, amount=Decimal("1.00"), actor=self.acct
        )
        self.assertEqual(req.workflow_code, WF_SUPPLIER_PAYMENT)
        payload = req.payload or {}
        self.assertEqual(payload.get("amount"), "1.00")
        self.assertEqual(payload.get("currency"), "AZN")
        self.assertEqual(payload.get("payee_id"), self.supplier.pk)
        self.assertEqual(payload.get("amount_requested_now"), "1.00")
        self.assertEqual(payload.get("liability_gross"), "1000.00")
        self.assertIn("expected_remainder", payload)
        self.assertEqual(payload.get("po_code"), "PO-D04-1")

        self.client.force_login(self.mgmt)
        page = self.client.get(reverse("erp:payment_approvals") + "?queue=ap")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, inv.code)
        self.assertContains(page, "1.00")
        self.assertContains(page, "Qalan (gözlənilən)")
        self.assertContains(page, "AP gözləyən təsdiq")
        self.assertContains(page, self.supplier.display_name)

        ApprovalService.decide(req, approved=True, decided_by=self.mgmt)
        req.refresh_from_db()
        self.assertEqual(req.status, ApprovalStatus.APPROVED)
        self.assertFalse(inv.payments.exists())
        self.assertIsNone((req.payload or {}).get("supplier_payment_id"))

    def test_incoming_finance_cancels_legacy_ar_without_double_post(self):
        co = ResidentCompany.objects.create(name="D04 Co", slug="d04-co", portal_active=True)
        party = party_for_company(co, ensure=True)
        charge = Charge.objects.create(
            party=party,
            source=ChargeSource.RENT,
            description="rent",
            amount=Decimal("1000.00"),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(party, [charge.pk], apply_vat=False)
        confirm_invoice(inv)
        inv.refresh_from_db()
        self.assertEqual(invoice_balance(inv), Decimal("1000.00"))

        legacy = ApprovalService.request(
            workflow_code="finance.payment",
            requested_by=self.acct,
            entity=inv,
            payload={
                "invoice_id": inv.pk,
                "invoice_code": inv.code,
                "amount": "400.00",
                "method": "bank",
            },
        )
        payment = record_incoming_payment_verified(
            invoice=inv, amount=Decimal("400.00"), actor=self.acct, reference="FIN-400"
        )
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, ApprovalStatus.CANCELLED)
        self.assertEqual(invoice_balance(inv), Decimal("600.00"))
        self.assertEqual(inv.payments.count(), 1)
        self.assertEqual(payment.amount, Decimal("400.00"))
