"""Phase 4.3.8 — Django Admin financial mutation gate."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.billing.models import Charge, ChargeSource, Invoice, InvoiceLine, InvoiceStatus, Payment
from apps.billing.services import confirm_invoice, generate_invoice_from_charges, record_payment
from apps.parties.models import Party, PartyType
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


def _grant_view_perms(user, *models):
    for model in models:
        ct = ContentType.objects.get_for_model(model)
        for codename in (f"view_{model._meta.model_name}", f"add_{model._meta.model_name}",
                         f"change_{model._meta.model_name}", f"delete_{model._meta.model_name}"):
            perm = Permission.objects.filter(content_type=ct, codename=codename).first()
            if perm:
                user.user_permissions.add(perm)


class Phase438AdminSecurityTests(TestCase):
    def setUp(self):
        self.party = Party.objects.create(legal_name="AdminGate Co", party_type=PartyType.ORGANIZATION)
        self.superuser = User.objects.create_superuser(
            username="p438-su", email="p438su@test.az", password="x"
        )
        self.staff = User.objects.create_user(
            username="p438-staff",
            email="p438staff@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        _grant_view_perms(self.staff, Payment, Invoice, InvoiceLine, Charge, ApprovalRequest)

        charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="Gate rent",
            amount=Decimal("100.00"),
            currency="AZN",
        )
        self.invoice = generate_invoice_from_charges(self.party, [charge.pk], apply_vat=False)
        confirm_invoice(self.invoice)
        self.line = self.invoice.lines.first()
        self.payment = Payment.objects.create(
            invoice=self.invoice,
            party=self.party,
            amount=Decimal("10.00"),
            currency="AZN",
            method="bank",
            reference="SEED",
        )
        self.approval = ApprovalService.request(
            workflow_code="finance.payment",
            requested_by=self.staff,
            entity=self.invoice,
            payload={"invoice_id": self.invoice.pk, "amount": "50.00"},
        )

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c

    def _assert_admin_mutation_denied(self, resp):
        # Django Admin redirects (302) to changelist/login when permission is denied; 403 also OK.
        self.assertIn(resp.status_code, {403, 302})
        if resp.status_code == 302:
            loc = resp["Location"]
            self.assertNotIn("/add/", loc)

    def test_payment_admin_add_change_delete_denied_superuser(self):
        c = self._client(self.superuser)
        before_count = Payment.objects.count()
        add = c.get(reverse("admin:billing_payment_add"))
        self._assert_admin_mutation_denied(add)
        add_post = c.post(
            reverse("admin:billing_payment_add"),
            {
                "invoice": self.invoice.pk,
                "party": self.party.pk,
                "amount": "999.00",
                "currency": "AZN",
                "paid_at": timezone.localdate().isoformat(),
                "method": "bank",
                "reference": "HACK-ADD",
                "notes": "",
            },
        )
        self._assert_admin_mutation_denied(add_post)
        self.assertEqual(Payment.objects.count(), before_count)

        post_change = c.post(
            reverse("admin:billing_payment_change", args=[self.payment.pk]),
            {
                "invoice": self.invoice.pk,
                "party": self.party.pk,
                "amount": "999.00",
                "currency": "AZN",
                "paid_at": timezone.localdate().isoformat(),
                "method": "bank",
                "reference": "HACK",
                "notes": "",
            },
        )
        self._assert_admin_mutation_denied(post_change)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.amount, Decimal("10.00"))
        delete = c.post(
            reverse("admin:billing_payment_delete", args=[self.payment.pk]),
            {"post": "yes"},
        )
        self._assert_admin_mutation_denied(delete)
        self.assertTrue(Payment.objects.filter(pk=self.payment.pk).exists())

    def test_payment_changelist_readable(self):
        c = self._client(self.superuser)
        resp = c.get(reverse("admin:billing_payment_changelist"))
        self.assertEqual(resp.status_code, 200)

    def test_invoice_status_total_not_mutable_via_admin(self):
        c = self._client(self.superuser)
        before_status = self.invoice.status
        before_total = self.invoice.total
        resp = c.post(
            reverse("admin:billing_invoice_change", args=[self.invoice.pk]),
            {
                "code": self.invoice.code,
                "party": self.party.pk,
                "status": InvoiceStatus.PAID,
                "total": "1.00",
                "currency": "AZN",
                "notes": "hack",
            },
        )
        self.assertIn(resp.status_code, {403, 302})
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, before_status)
        self.assertEqual(self.invoice.total, before_total)
        self.assertNotEqual(self.invoice.status, InvoiceStatus.PAID)

    def test_invoice_line_standalone_add_denied(self):
        c = self._client(self.superuser)
        resp = c.get(reverse("admin:billing_invoiceline_add"))
        self._assert_admin_mutation_denied(resp)
        resp_post = c.post(
            reverse("admin:billing_invoiceline_add"),
            {
                "invoice": self.invoice.pk,
                "description": "Forged line",
                "amount": "500.00",
            },
        )
        self._assert_admin_mutation_denied(resp_post)
        self.assertFalse(InvoiceLine.objects.filter(description="Forged line").exists())

    def test_invoice_line_change_delete_denied(self):
        c = self._client(self.superuser)
        old_amt = self.line.amount
        resp = c.post(
            reverse("admin:billing_invoiceline_change", args=[self.line.pk]),
            {"invoice": self.invoice.pk, "description": self.line.description, "amount": "777.00"},
        )
        self.assertIn(resp.status_code, {403, 302})
        self.line.refresh_from_db()
        self.assertEqual(self.line.amount, old_amt)
        del_resp = c.post(
            reverse("admin:billing_invoiceline_delete", args=[self.line.pk]), {"post": "yes"}
        )
        self.assertIn(del_resp.status_code, {403, 302})
        self.assertTrue(InvoiceLine.objects.filter(pk=self.line.pk).exists())

    def test_approval_request_forge_denied(self):
        c = self._client(self.superuser)
        add = c.get(reverse("admin:workflows_approvalrequest_add"))
        self._assert_admin_mutation_denied(add)
        change = c.post(
            reverse("admin:workflows_approvalrequest_change", args=[self.approval.pk]),
            {
                "workflow_code": "finance.payment",
                "status": ApprovalStatus.APPROVED,
                "payload": '{"invoice_id": 1, "amount": "100"}',
            },
        )
        self._assert_admin_mutation_denied(change)
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, ApprovalStatus.PENDING)

    def test_charge_admin_add_denied(self):
        c = self._client(self.superuser)
        resp = c.get(reverse("admin:billing_charge_add"))
        self._assert_admin_mutation_denied(resp)
        before = Charge.objects.count()
        post = c.post(
            reverse("admin:billing_charge_add"),
            {
                "party": self.party.pk,
                "source": ChargeSource.RENT,
                "description": "Admin forged charge",
                "amount": "999.00",
                "currency": "AZN",
            },
        )
        self._assert_admin_mutation_denied(post)
        self.assertEqual(Charge.objects.count(), before)
        self.assertFalse(Charge.objects.filter(description="Admin forged charge").exists())

    def test_staff_accountant_payment_add_denied(self):
        c = self._client(self.staff)
        resp = c.get(reverse("admin:billing_payment_add"))
        self._assert_admin_mutation_denied(resp)

    def test_legitimate_record_payment_still_works(self):
        manager = User.objects.create_user(
            username="p438-mgmt",
            email="p438m@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        req = ApprovalService.request(
            workflow_code="finance.payment",
            requested_by=self.staff,
            entity=self.invoice,
            payload={
                "invoice_id": self.invoice.pk,
                "amount": str(self.invoice.total - Decimal("10.00")),
                "method": "bank",
                "reference": "LEGIT",
            },
        )
        ApprovalService.decide(req, approved=True, decided_by=manager)
        req.refresh_from_db()
        pay = record_payment(
            invoice=self.invoice,
            amount=self.invoice.total - Decimal("10.00"),
            approval_request=req,
            method="bank",
            reference="LEGIT",
        )
        self.assertEqual(pay.reference, "LEGIT")
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, InvoiceStatus.PAID)
