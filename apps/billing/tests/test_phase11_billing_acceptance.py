"""Phase 11 — charge → invoice → payment allocation → resident balance (A–G)."""

from __future__ import annotations

import threading
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership, ensure_portal_memberships
from apps.billing.models import Charge, ChargeSource, Invoice, InvoiceLine, InvoiceStatus, Payment
from apps.billing.services import (
    confirm_invoice,
    generate_invoice_from_charges,
    invoice_balance,
    mark_overdue_invoices,
    record_payment,
    void_invoice,
)
from apps.core.services import DomainError
from apps.leases.lease_ops import ensure_deposit_charge, generate_monthly_lease_charges
from apps.leases.models import Lease, LeaseStatus
from apps.maintenance.models import WorkOrder, WorkOrderStatus
from apps.maintenance.services import WorkOrderService
from apps.parties.models import Party, PartyType
from apps.parties.resolvers import party_for_company
from apps.property.models import Building, Floor, Space
from apps.residents.models import ResidentCompany
from apps.workflows.services import ApprovalService

User = get_user_model()


def _approved_pay(invoice, amount, *, accountant, manager, reference=""):
    req = ApprovalService.request(
        workflow_code="finance.payment",
        requested_by=accountant,
        entity=invoice,
        payload={
            "invoice_id": invoice.pk,
            "invoice_code": invoice.code,
            "amount": str(amount),
            "method": "bank",
            "reference": reference,
        },
    )
    ApprovalService.decide(req, approved=True, decided_by=manager)
    req.refresh_from_db()
    return req


class Phase11BillingAcceptanceTests(TestCase):
    """A, B, D, E, F, G + Finance/portal walkthrough (apply_vat=False for A)."""

    def setUp(self):
        self.accountant = User.objects.create_user(
            username="p11-acc",
            email="p11-acc@test.az",
            password="Pass12345!",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.manager = User.objects.create_user(
            username="p11-mgmt",
            email="p11-mgmt@test.az",
            password="Pass12345!",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.reception = User.objects.create_user(
            username="p11-rec",
            email="p11-rec@test.az",
            password="Pass12345!",
            role=Role.RECEPTION,
            is_staff=True,
        )
        self.company = ResidentCompany.objects.create(
            name="P11 Co A", slug="p11-coa", portal_active=True
        )
        self.other_company = ResidentCompany.objects.create(
            name="P11 Co B", slug="p11-cob", portal_active=True
        )
        self.party = party_for_company(self.company, ensure=True)
        self.other_party = party_for_company(self.other_company, ensure=True)
        building = Building.objects.create(code="P11B", name="P11B")
        floor = Floor.objects.create(building=building, code="P11F", name="1")
        self.space = Space.objects.create(
            code="P11S",
            name="P11S",
            floor=floor,
            area_m2=Decimal("100"),
            rentable_area_m2=Decimal("100"),
            base_rent_rate=Decimal("10"),
            service_charge_rate=Decimal("0"),
        )
        self.lease = Lease.objects.create(
            code="LS-P11",
            party=self.party,
            space=self.space,
            status=LeaseStatus.ACTIVE,
            billing_active=True,
            start_date=date(2026, 1, 1),
            rent_rate_per_m2=Decimal("10"),
            service_rate_per_m2=Decimal("0"),
            rent=Decimal("1000"),
            service_charge=Decimal("0"),
            deposit=Decimal("2000"),
            deposit_months=2,
            parking_included_free=True,
            currency="AZN",
        )
        self.resident = User.objects.create_user(
            username="p11-res",
            email="p11-res@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_membership(self.resident, self.company)
        self.fin = Client()
        self.fin.force_login(self.accountant)
        self.portal = Client()
        self.portal.force_login(self.resident)

    def test_A_reconciliation_1000_partial_then_settle(self):
        """A: 1000 AZN charge → invoice due 1000 → 400 → 600 → 0 (VAT off)."""
        charge = Charge.objects.create(
            party=self.party,
            lease=self.lease,
            source=ChargeSource.RENT,
            description="P11 rent Jan · LS-P11",
            amount=Decimal("1000.00"),
            currency="AZN",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        inv = generate_invoice_from_charges(self.party, [charge.pk], apply_vat=False)
        self.assertEqual(inv.status, InvoiceStatus.DRAFT)
        self.assertEqual(inv.total, Decimal("1000.00"))

        # Draft not yet owed in portal
        self.portal.post(reverse("portal:choose_companies"), {"choice": str(self.company.pk)})
        draft_page = self.portal.get(reverse("portal:invoices"))
        self.assertEqual(draft_page.status_code, 200)
        self.assertNotContains(draft_page, inv.code)
        self.assertEqual(draft_page.context["open_total"], Decimal("0"))

        confirm_invoice(inv)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.ISSUED)
        self.assertEqual(invoice_balance(inv), Decimal("1000.00"))

        issued_page = self.portal.get(reverse("portal:invoices"))
        self.assertContains(issued_page, inv.code)
        self.assertEqual(issued_page.context["open_total"], Decimal("1000.00"))
        self.assertContains(issued_page, "Açıq borc")

        fin_detail = self.fin.get(reverse("finance:invoice_detail", kwargs={"code": inv.code}))
        self.assertEqual(fin_detail.status_code, 200)
        self.assertEqual(fin_detail.context["balance"], Decimal("1000.00"))

        r1 = _approved_pay(
            inv, Decimal("400.00"), accountant=self.accountant, manager=self.manager, reference="P11-400"
        )
        record_payment(
            invoice=inv, amount=Decimal("400.00"), approval_request=r1, method="bank", reference="P11-400"
        )
        inv.refresh_from_db()
        self.assertEqual(invoice_balance(inv), Decimal("600.00"))
        self.assertEqual(inv.status, InvoiceStatus.ISSUED)

        mid = self.portal.get(reverse("portal:invoices"))
        self.assertEqual(mid.context["open_total"], Decimal("600.00"))
        paid_row = next(r for r in mid.context["invoice_rows"] if r["invoice"].pk == inv.pk)
        self.assertEqual(paid_row["paid"], Decimal("400.00"))
        self.assertEqual(paid_row["balance"], Decimal("600.00"))

        r2 = _approved_pay(
            inv, Decimal("600.00"), accountant=self.accountant, manager=self.manager, reference="P11-600"
        )
        record_payment(
            invoice=inv, amount=Decimal("600.00"), approval_request=r2, method="bank", reference="P11-600"
        )
        inv.refresh_from_db()
        self.assertEqual(invoice_balance(inv), Decimal("0.00"))
        self.assertEqual(inv.status, InvoiceStatus.PAID)
        self.assertEqual(
            sum(p.amount for p in Payment.objects.filter(invoice=inv)),
            Decimal("1000.00"),
        )

        settled = self.portal.get(reverse("portal:invoices"))
        self.assertContains(settled, inv.code)
        self.assertEqual(settled.context["open_total"], Decimal("0"))

        # Replay same approval must not double-apply
        record_payment(
            invoice=inv, amount=Decimal("600.00"), approval_request=r2, method="bank", reference="P11-600"
        )
        self.assertEqual(Payment.objects.filter(invoice=inv).count(), 2)
        self.assertEqual(invoice_balance(inv), Decimal("0.00"))

        # Two genuine equal payments remain possible on a fresh invoice
        c2 = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="twin",
            amount=Decimal("200.00"),
            currency="AZN",
        )
        inv2 = generate_invoice_from_charges(self.party, [c2.pk], apply_vat=False)
        confirm_invoice(inv2)
        for i, amt in enumerate((Decimal("100.00"), Decimal("100.00"))):
            req = _approved_pay(
                inv2, amt, accountant=self.accountant, manager=self.manager, reference=f"T{i}"
            )
            record_payment(invoice=inv2, amount=amt, approval_request=req, method="bank", reference=f"T{i}")
        self.assertEqual(Payment.objects.filter(invoice=inv2).count(), 2)
        self.assertEqual(invoice_balance(inv2), Decimal("0.00"))

    def test_B_two_periods_replay_and_catchup(self):
        """B: consecutive periods once each; replay + delayed catch-up idempotent."""
        s1 = generate_monthly_lease_charges(as_of=date(2026, 1, 3))
        self.assertGreaterEqual(s1["created"], 1)
        rent_jan = Charge.objects.filter(
            lease=self.lease, source=ChargeSource.RENT, period_start=date(2026, 1, 1)
        )
        self.assertEqual(rent_jan.count(), 1)
        self.assertEqual(rent_jan.get().amount, Decimal("1000.00"))

        replay = generate_monthly_lease_charges(as_of=date(2026, 1, 4))
        self.assertEqual(replay["created"], 0)
        self.assertEqual(rent_jan.count(), 1)

        # Missed February, then catch-up
        s2 = generate_monthly_lease_charges(as_of=date(2026, 2, 2))
        self.assertGreaterEqual(s2["created"], 1)
        rent_feb = Charge.objects.filter(
            lease=self.lease, source=ChargeSource.RENT, period_start=date(2026, 2, 1)
        )
        self.assertEqual(rent_feb.count(), 1)

        generate_monthly_lease_charges(as_of=date(2026, 2, 5))
        self.assertEqual(
            Charge.objects.filter(lease=self.lease, source=ChargeSource.RENT).count(),
            2,
        )

        # Future-start signed lease: no premature rent
        future = Lease.objects.create(
            code="LS-P11-FUT",
            party=self.party,
            space=self.space,
            status=LeaseStatus.ACTIVE,
            billing_active=True,
            start_date=date(2026, 6, 1),
            rent_rate_per_m2=Decimal("10"),
            rent=Decimal("1000"),
            parking_included_free=True,
        )
        generate_monthly_lease_charges(as_of=date(2026, 3, 2))
        self.assertFalse(
            Charge.objects.filter(lease=future, source=ChargeSource.RENT).exists()
        )

        # Rate amendment affects future only; issued history frozen
        jan = rent_jan.get()
        inv = generate_invoice_from_charges(self.party, [jan.pk], apply_vat=False)
        confirm_invoice(inv)
        frozen_total = inv.total
        self.lease.rent_rate_per_m2 = Decimal("12")
        self.lease.rent = Decimal("1200")
        self.lease.save(update_fields=["rent_rate_per_m2", "rent", "updated_at"])
        inv.refresh_from_db()
        self.assertEqual(inv.total, frozen_total)
        self.assertEqual(InvoiceLine.objects.get(invoice=inv, charge=jan).amount, Decimal("1000.00"))

        # Termination stops future periods (March already created above for future-lease probe)
        self.lease.billing_active = False
        self.lease.status = LeaseStatus.TERMINATED
        self.lease.save(update_fields=["billing_active", "status", "updated_at"])
        before_apr = Charge.objects.filter(lease=self.lease, source=ChargeSource.RENT).count()
        generate_monthly_lease_charges(as_of=date(2026, 4, 2))
        self.assertFalse(
            Charge.objects.filter(
                lease=self.lease, source=ChargeSource.RENT, period_start=date(2026, 4, 1)
            ).exists()
        )
        self.assertEqual(
            Charge.objects.filter(lease=self.lease, source=ChargeSource.RENT).count(),
            before_apr,
        )

    def test_D_draft_future_due_overdue_portal_outcomes(self):
        """D: draft hidden; future due open; overdue distinct."""
        c_draft = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="draft",
            amount=Decimal("50.00"),
            currency="AZN",
        )
        draft = generate_invoice_from_charges(self.party, [c_draft.pk], apply_vat=False)
        self.assertEqual(draft.status, InvoiceStatus.DRAFT)

        c_open = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="open",
            amount=Decimal("75.00"),
            currency="AZN",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        issued = generate_invoice_from_charges(self.party, [c_open.pk], apply_vat=False)
        confirm_invoice(issued)
        issued.due_date = timezone.localdate() + timedelta(days=20)
        issued.save(update_fields=["due_date"])

        c_od = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="overdue",
            amount=Decimal("90.00"),
            currency="AZN",
            period_start=date(2025, 11, 1),
            period_end=date(2025, 11, 30),
        )
        overdue = generate_invoice_from_charges(self.party, [c_od.pk], apply_vat=False)
        confirm_invoice(overdue)
        overdue.due_date = timezone.localdate() - timedelta(days=5)
        overdue.save(update_fields=["due_date"])
        mark_overdue_invoices()
        overdue.refresh_from_db()
        self.assertEqual(overdue.status, InvoiceStatus.OVERDUE)

        self.portal.post(reverse("portal:choose_companies"), {"choice": str(self.company.pk)})
        page = self.portal.get(reverse("portal:invoices"))
        self.assertNotContains(page, draft.code)
        self.assertContains(page, issued.code)
        self.assertContains(page, overdue.code)
        self.assertContains(page, "Vaxtı keçmiş")
        ctx = page.context
        self.assertEqual(ctx["overdue_total"], Decimal("90.00"))
        self.assertEqual(ctx["open_total"], Decimal("165.00"))  # 75 + 90
        od_row = next(r for r in ctx["invoice_rows"] if r["invoice"].pk == overdue.pk)
        self.assertTrue(od_row["is_overdue"])
        self.assertEqual(od_row["balance"], Decimal("90.00"))

    def test_E_company_isolation_and_readonly_staff(self):
        """E: no cross-company balance; reception cannot mutate finance."""
        Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="mine",
            amount=Decimal("111.00"),
            currency="AZN",
        )
        other_charge = Charge.objects.create(
            party=self.other_party,
            source=ChargeSource.RENT,
            description="theirs SECRET-P11",
            amount=Decimal("999.00"),
            currency="AZN",
        )
        mine = generate_invoice_from_charges(
            self.party,
            list(Charge.objects.filter(party=self.party, invoice__isnull=True).values_list("pk", flat=True)),
            apply_vat=False,
        )
        confirm_invoice(mine)
        theirs = generate_invoice_from_charges(self.other_party, [other_charge.pk], apply_vat=False)
        confirm_invoice(theirs)

        self.portal.post(reverse("portal:choose_companies"), {"choice": str(self.company.pk)})
        page = self.portal.get(reverse("portal:invoices"))
        self.assertContains(page, mine.code)
        self.assertNotContains(page, theirs.code)
        self.assertNotContains(page, "SECRET-P11")
        self.assertNotContains(page, "999.00")
        self.assertEqual(page.context["open_total"], Decimal("111.00"))

        # Multi-company: single vs combined
        ensure_portal_memberships(self.resident, [self.company, self.other_company])
        self.portal.post(reverse("portal:choose_companies"), {"choice": str(self.company.pk)})
        single = self.portal.get(reverse("portal:invoices"))
        self.assertEqual(single.context["open_total"], Decimal("111.00"))
        self.portal.post(reverse("portal:choose_companies"), {"choice": "all"})
        combined = self.portal.get(reverse("portal:invoices"))
        self.assertEqual(combined.context["open_total"], Decimal("1110.00"))
        self.assertContains(combined, mine.code)
        self.assertContains(combined, theirs.code)

        # Read-only staff (reception) cannot issue / pay
        rec = Client()
        rec.force_login(self.reception)
        before = Invoice.objects.count()
        resp = rec.post(
            reverse("finance:charges"),
            {"action": "invoice_party", "party_id": self.party.pk},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Invoice.objects.count(), before)
        pay_before = Payment.objects.count()
        resp2 = rec.post(
            reverse("finance:invoice_detail", kwargs={"code": mine.code}),
            {"action": "confirm"},
        )
        self.assertEqual(resp2.status_code, 302)
        self.assertEqual(Payment.objects.count(), pay_before)

    def test_F_failed_confirm_keeps_draft_consistent(self):
        """F: JE failure rolls back ISSUED; no success path."""
        charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="fail-je",
            amount=Decimal("33.00"),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(self.party, [charge.pk], apply_vat=False)
        with patch(
            "apps.accounting.services.AccountingService.journal_from_invoice",
            side_effect=RuntimeError("JE boom"),
        ):
            with self.assertRaises(DomainError):
                confirm_invoice(inv)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.DRAFT)
        charge.refresh_from_db()
        self.assertEqual(charge.invoice_id, inv.pk)

    def test_G_deposit_bundled_parking_and_billable_wo(self):
        """G: deposit once; free parking no charge; billable WO creates charge."""
        dep = ensure_deposit_charge(self.lease)
        self.assertIsNotNone(dep)
        self.assertEqual(dep.source, ChargeSource.DEPOSIT)
        self.assertEqual(dep.amount, Decimal("2000.00"))
        self.assertEqual(dep.period_start, self.lease.start_date)
        again = ensure_deposit_charge(self.lease)
        self.assertEqual(again.pk, dep.pk)
        self.assertEqual(
            Charge.objects.filter(lease=self.lease, source=ChargeSource.DEPOSIT).count(),
            1,
        )

        generate_monthly_lease_charges(as_of=date(2026, 1, 2))
        self.assertFalse(
            Charge.objects.filter(lease=self.lease, source=ChargeSource.PARKING).exists()
        )

        # Deposit cannot mix with rent on one invoice
        rent = Charge.objects.get(
            lease=self.lease, source=ChargeSource.RENT, period_start=date(2026, 1, 1)
        )
        with self.assertRaises(DomainError):
            generate_invoice_from_charges(self.party, [dep.pk, rent.pk], apply_vat=False)

        # Finance UI invoices non-deposit first
        resp = self.fin.post(
            reverse("finance:charges"),
            {"action": "invoice_party", "party_id": self.party.pk},
        )
        self.assertEqual(resp.status_code, 302)
        rent.refresh_from_db()
        dep.refresh_from_db()
        self.assertIsNotNone(rent.invoice_id)
        self.assertIsNone(dep.invoice_id)

        wo = WorkOrder.objects.create(
            code="WO-P11-1",
            title="Billable fix",
            status=WorkOrderStatus.IN_PROGRESS,
            party=self.party,
            space=self.space,
            billable=True,
            resident_amount=Decimal("150.00"),
        )
        WorkOrderService.set_status(
            wo, WorkOrderStatus.COMPLETED, actor=self.accountant, note="done"
        )
        wo_charge = Charge.objects.get(source=ChargeSource.WORK_ORDER, work_order=wo)
        self.assertEqual(wo_charge.amount, Decimal("150.00"))
        self.assertEqual(wo_charge.party_id, self.party.pk)

    def test_operator_http_walkthrough_routes(self):
        """Authenticated Finance → charges → draft → confirm → portal owed."""
        Charge.objects.create(
            party=self.party,
            lease=self.lease,
            source=ChargeSource.RENT,
            description="walk rent",
            amount=Decimal("250.00"),
            currency="AZN",
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
        )
        self.assertEqual(self.fin.get(reverse("finance:home")).status_code, 200)
        self.assertEqual(self.fin.get(reverse("finance:charges")).status_code, 200)
        resp = self.fin.post(
            reverse("finance:charges"),
            {"action": "invoice_party", "party_id": self.party.pk},
        )
        self.assertEqual(resp.status_code, 302)
        inv = Invoice.objects.filter(party=self.party).latest("id")
        self.assertEqual(inv.status, InvoiceStatus.DRAFT)
        detail = self.fin.get(reverse("finance:invoice_detail", kwargs={"code": inv.code}))
        # Finance UI applies A.5 VAT by default (250 net → 295 gross)
        self.assertEqual(detail.context["invoice"].total, Decimal("295.00"))
        self.assertEqual(detail.context["balance"], Decimal("295.00"))
        confirm = self.fin.post(
            reverse("finance:invoice_detail", kwargs={"code": inv.code}),
            {"action": "confirm"},
        )
        self.assertEqual(confirm.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.ISSUED)

        self.portal.post(reverse("portal:choose_companies"), {"choice": str(self.company.pk)})
        portal = self.portal.get(reverse("portal:invoices"))
        self.assertContains(portal, inv.code)
        self.assertEqual(portal.context["open_total"], Decimal("295.00"))
        self.assertContains(portal, "Son ödəniş")


class Phase11InvoiceConcurrencyTests(TransactionTestCase):
    """C: two operators invoice the same charge — one effective line."""

    def setUp(self):
        self.party = Party.objects.create(legal_name="P11 Conc", party_type=PartyType.ORGANIZATION)
        self.charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="race charge",
            amount=Decimal("1000.00"),
            currency="AZN",
        )

    def test_C_concurrent_invoice_same_charge_one_wins(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL row-level locks")

        party_id = self.party.pk
        charge_id = self.charge.pk
        barrier = threading.Barrier(2, timeout=20)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker(tag: str):
            connections.close_all()
            try:
                barrier.wait()
                party = Party.objects.get(pk=party_id)
                inv = generate_invoice_from_charges(party, [charge_id], apply_vat=False)
                with lock:
                    outcomes.append(f"ok:{tag}:{inv.code}")
            except ValueError as exc:
                with lock:
                    outcomes.append(f"err:{tag}:{exc}")
            except Exception as exc:  # noqa: BLE001
                with lock:
                    outcomes.append(f"{type(exc).__name__}:{tag}:{exc}")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(t,)) for t in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)
            self.assertFalse(t.is_alive())

        ok = [o for o in outcomes if o.startswith("ok:")]
        err = [o for o in outcomes if o.startswith("err:")]
        self.assertEqual(len(ok), 1, outcomes)
        self.assertEqual(len(err), 1, outcomes)
        self.charge.refresh_from_db()
        self.assertIsNotNone(self.charge.invoice_id)
        self.assertEqual(
            InvoiceLine.objects.filter(charge_id=charge_id).count(),
            1,
        )
        self.assertEqual(
            Invoice.objects.filter(party_id=party_id, status=InvoiceStatus.DRAFT).count(),
            1,
        )
        inv = Invoice.objects.get(pk=self.charge.invoice_id)
        self.assertEqual(inv.total, Decimal("1000.00"))


class Phase11CrossPartyPaymentTests(TestCase):
    """Payment cannot be allocated to another company's invoice."""

    def setUp(self):
        self.accountant = User.objects.create_user(
            username="p11x-acc", email="p11x@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        self.manager = User.objects.create_user(
            username="p11x-m", email="p11xm@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        self.p1 = Party.objects.create(legal_name="P11X1", party_type=PartyType.ORGANIZATION)
        self.p2 = Party.objects.create(legal_name="P11X2", party_type=PartyType.ORGANIZATION)
        c1 = Charge.objects.create(
            party=self.p1, source=ChargeSource.RENT, description="a", amount=Decimal("100"), currency="AZN"
        )
        c2 = Charge.objects.create(
            party=self.p2, source=ChargeSource.RENT, description="b", amount=Decimal("100"), currency="AZN"
        )
        self.inv1 = generate_invoice_from_charges(self.p1, [c1.pk], apply_vat=False)
        confirm_invoice(self.inv1)
        self.inv2 = generate_invoice_from_charges(self.p2, [c2.pk], apply_vat=False)
        confirm_invoice(self.inv2)

    def test_approval_for_other_invoice_rejected(self):
        req = _approved_pay(
            self.inv2, Decimal("100"), accountant=self.accountant, manager=self.manager
        )
        with self.assertRaises(DomainError):
            record_payment(
                invoice=self.inv1, amount=Decimal("100"), approval_request=req, method="bank"
            )
        self.assertEqual(Payment.objects.filter(invoice=self.inv1).count(), 0)

    def test_overpay_rejected_no_unapplied_bucket(self):
        """Finance has not approved unapplied credit — overpay blocked."""
        req = _approved_pay(
            self.inv1, Decimal("150"), accountant=self.accountant, manager=self.manager
        )
        with self.assertRaises(DomainError):
            record_payment(
                invoice=self.inv1, amount=Decimal("150"), approval_request=req, method="bank"
            )
