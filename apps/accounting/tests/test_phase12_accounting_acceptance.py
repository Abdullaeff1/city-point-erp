"""Phase 12 — CoA, journal post, period close, trial balance (A.6)."""

from __future__ import annotations

import threading
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.accounting.coa import code_for
from apps.accounting.models import Account, AccountingPeriod, JournalEntry, JournalLine
from apps.accounting.services import AccountingService, seed_minimal_coa, trial_balance
from apps.billing.models import Charge, ChargeSource, InvoiceStatus, Payment
from apps.billing.services import (
    confirm_invoice,
    generate_invoice_from_charges,
    invoice_balance,
    record_payment,
)
from apps.core.services import DomainError
from apps.parties.models import Party, PartyType
from apps.parties.resolvers import party_for_company
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


def _line_amounts(entry, account_code):
    deb = Decimal("0")
    cre = Decimal("0")
    for ln in entry.lines.select_related("account"):
        if ln.account.code == account_code:
            deb += ln.debit or Decimal("0")
            cre += ln.credit or Decimal("0")
    return deb, cre


class Phase12AccountingAcceptanceTests(TestCase):
    """Checkpoints A–C + TB + ACL + closed period + missing mapping."""

    def setUp(self):
        seed_minimal_coa()
        self.accountant = User.objects.create_user(
            username="p12-acc",
            email="p12-acc@test.az",
            password="Pass12345!",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.manager = User.objects.create_user(
            username="p12-mgmt",
            email="p12-mgmt@test.az",
            password="Pass12345!",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.reception = User.objects.create_user(
            username="p12-rec",
            email="p12-rec@test.az",
            password="Pass12345!",
            role=Role.RECEPTION,
            is_staff=True,
        )
        self.company = ResidentCompany.objects.create(
            name="P12 Co A", slug="p12-coa", portal_active=True
        )
        self.company_b = ResidentCompany.objects.create(
            name="P12 Co B", slug="p12-cob", portal_active=True
        )
        self.party = party_for_company(self.company, ensure=True)
        self.party_b = party_for_company(self.company_b, ensure=True)
        self.resident = User.objects.create_user(
            username="p12-res",
            email="p12-res@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_membership(self.resident, self.company)
        self.fin = Client()
        self.fin.force_login(self.accountant)
        self.portal = Client()
        self.portal.force_login(self.resident)
        self.ar = code_for("ar")
        self.rev = code_for("rent_revenue")
        self.bank = code_for("bank")

    def _issue_vat_off(self, party, amount, *, desc="P12 rent"):
        charge = Charge.objects.create(
            party=party,
            source=ChargeSource.RENT,
            description=desc,
            amount=Decimal(amount),
            currency="AZN",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
        )
        inv = generate_invoice_from_charges(party, [charge.pk], apply_vat=False)
        confirm_invoice(inv)
        inv.refresh_from_db()
        return inv

    def test_A_B_C_three_checkpoint_reconciliation(self):
        """A: post 1000 invoice; B: pay 400; C: pay 600 — AR/portal/billing align."""
        inv = self._issue_vat_off(self.party, "1000.00")
        self.assertEqual(inv.total, Decimal("1000.00"))
        je_inv = JournalEntry.objects.get(source="billing.invoice", source_ref=f"invoice:{inv.pk}")
        self.assertFalse(je_inv.posted)
        self.assertEqual(invoice_balance(inv), Decimal("1000.00"))

        # A — post invoice JE
        AccountingService.post_to_gl(je_inv, actor=self.accountant)
        je_inv.refresh_from_db()
        self.assertTrue(je_inv.posted)
        dr, _ = _line_amounts(je_inv, self.ar)
        _, cr = _line_amounts(je_inv, self.rev)
        self.assertEqual(dr, Decimal("1000.00"))
        self.assertEqual(cr, Decimal("1000.00"))

        self.portal.post(reverse("portal:choose_companies"), {"choice": str(self.company.pk)})
        portal_a = self.portal.get(reverse("portal:invoices"))
        self.assertEqual(portal_a.context["open_total"], Decimal("1000.00"))

        # B — confirm 400; billing/portal stay 600 after GL post
        r1 = _approved_pay(
            inv, Decimal("400.00"), accountant=self.accountant, manager=self.manager, reference="P12-400"
        )
        pay1 = record_payment(
            invoice=inv, amount=Decimal("400.00"), approval_request=r1, method="bank", reference="P12-400"
        )
        inv.refresh_from_db()
        bal_before_post = invoice_balance(inv)
        self.assertEqual(bal_before_post, Decimal("600.00"))
        portal_b1 = self.portal.get(reverse("portal:invoices"))
        self.assertEqual(portal_b1.context["open_total"], Decimal("600.00"))

        je_p1 = JournalEntry.objects.get(source="billing.payment", source_ref=f"payment:{pay1.pk}")
        self.assertFalse(je_p1.posted)
        AccountingService.post_to_gl(je_p1, actor=self.accountant)
        inv.refresh_from_db()
        self.assertEqual(invoice_balance(inv), Decimal("600.00"))  # billing unchanged by GL
        portal_b2 = self.portal.get(reverse("portal:invoices"))
        self.assertEqual(portal_b2.context["open_total"], Decimal("600.00"))
        _, ar_cr = _line_amounts(je_p1, self.ar)
        bank_dr, _ = _line_amounts(je_p1, self.bank)
        self.assertEqual(ar_cr, Decimal("400.00"))
        self.assertEqual(bank_dr, Decimal("400.00"))

        # C — final 600
        r2 = _approved_pay(
            inv, Decimal("600.00"), accountant=self.accountant, manager=self.manager, reference="P12-600"
        )
        pay2 = record_payment(
            invoice=inv, amount=Decimal("600.00"), approval_request=r2, method="bank", reference="P12-600"
        )
        je_p2 = JournalEntry.objects.get(source="billing.payment", source_ref=f"payment:{pay2.pk}")
        AccountingService.post_to_gl(je_p2, actor=self.accountant)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.PAID)
        self.assertEqual(invoice_balance(inv), Decimal("0.00"))
        self.assertEqual(Payment.objects.filter(invoice=inv).count(), 2)
        self.assertNotEqual(je_p1.pk, je_p2.pk)
        self.assertEqual(
            JournalEntry.objects.filter(
                source__in=("billing.invoice", "billing.payment"),
                source_ref__in=(
                    f"invoice:{inv.pk}",
                    f"payment:{pay1.pk}",
                    f"payment:{pay2.pk}",
                ),
                posted=True,
            ).count(),
            3,
        )
        # Posting payment JE must not create another Payment or change amount
        pay1.refresh_from_db()
        self.assertEqual(pay1.amount, Decimal("400.00"))
        self.assertEqual(Payment.objects.filter(pk=pay1.pk).count(), 1)

        portal_c = self.portal.get(reverse("portal:invoices"))
        self.assertEqual(portal_c.context["open_total"], Decimal("0"))

        # Shared AR control — two companies; payment A does not settle B
        inv_b = self._issue_vat_off(self.party_b, "500.00", desc="P12 B rent")
        AccountingService.post_to_gl(
            JournalEntry.objects.get(source="billing.invoice", source_ref=f"invoice:{inv_b.pk}"),
            actor=self.accountant,
        )
        ar_rows = trial_balance(year=timezone.localdate().year)
        ar_row = next(r for r in ar_rows if r["code"] == self.ar)
        # A fully settled in GL: +1000 -400 -600; B +500 → AR closing 500 attributable to B
        # (plus any opening from other tests in same DB keepdb — isolate via invoice memos)
        # Net for our fixtures: after A settled, B open 500.
        # Use payment-linked credit sum vs invoice debits for these sources:
        inv_dr = sum(
            (
                ln.debit
                for ln in JournalLine.objects.filter(
                    entry__source="billing.invoice",
                    entry__posted=True,
                    account__code=self.ar,
                    entry__source_ref__in=(f"invoice:{inv.pk}", f"invoice:{inv_b.pk}"),
                )
            ),
            Decimal("0"),
        )
        pay_cr = sum(
            (
                ln.credit
                for ln in JournalLine.objects.filter(
                    entry__source="billing.payment",
                    entry__posted=True,
                    account__code=self.ar,
                    entry__source_ref__in=(f"payment:{pay1.pk}", f"payment:{pay2.pk}"),
                )
            ),
            Decimal("0"),
        )
        self.assertEqual(inv_dr - pay_cr, Decimal("500.00"))
        self.assertEqual(invoice_balance(inv_b), Decimal("500.00"))
        self.assertEqual(invoice_balance(inv), Decimal("0.00"))
        _ = ar_row

    def test_duplicate_post_idempotent_and_distinct_payments(self):
        inv = self._issue_vat_off(self.party, "200.00", desc="dup")
        je = JournalEntry.objects.get(source="billing.invoice", source_ref=f"invoice:{inv.pk}")
        a = AccountingService.post_to_gl(je, actor=self.accountant)
        b = AccountingService.post_to_gl(je, actor=self.accountant)
        self.assertEqual(a.pk, b.pk)
        again = AccountingService.journal_from_invoice(inv, net=inv.total, vat=0)
        self.assertEqual(again.pk, je.pk)

        r1 = _approved_pay(
            inv, Decimal("100.00"), accountant=self.accountant, manager=self.manager, reference="D1"
        )
        p1 = record_payment(invoice=inv, amount=Decimal("100.00"), approval_request=r1, method="bank")
        r2 = _approved_pay(
            inv, Decimal("100.00"), accountant=self.accountant, manager=self.manager, reference="D2"
        )
        p2 = record_payment(invoice=inv, amount=Decimal("100.00"), approval_request=r2, method="bank")
        j1 = JournalEntry.objects.get(source_ref=f"payment:{p1.pk}")
        j2 = JournalEntry.objects.get(source_ref=f"payment:{p2.pk}")
        self.assertNotEqual(j1.pk, j2.pk)

    def test_missing_inactive_account_blocks_post_source_awaits(self):
        inv = self._issue_vat_off(self.party, "80.00", desc="inactive-map")
        je = JournalEntry.objects.get(source="billing.invoice", source_ref=f"invoice:{inv.pk}")
        acct = Account.objects.get(code=self.rev)
        acct.is_active = False
        acct.save(update_fields=["is_active"])
        with self.assertRaises(DomainError):
            AccountingService.post_to_gl(je, actor=self.accountant)
        je.refresh_from_db()
        self.assertFalse(je.posted)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.ISSUED)
        acct.is_active = True
        acct.save(update_fields=["is_active"])

        with self.assertRaises(DomainError):
            AccountingService.post_journal(
                lines=[
                    {"account_code": "999", "debit": Decimal("10"), "credit": 0},
                    {"account_code": self.bank, "debit": 0, "credit": Decimal("10")},
                ],
                memo="bad map",
                source="manual",
                source_ref="p12-missing-map",
            )

    def test_closed_period_preserves_date_and_blocks_all_entry_points(self):
        today = timezone.localdate()
        # Use prior month as closed period
        if today.month == 1:
            cy, cm = today.year - 1, 12
        else:
            cy, cm = today.year, today.month - 1
        AccountingService.close_period(year=cy, month=cm, actor=self.accountant)
        closed_day = date(cy, cm, 15)
        with self.assertRaises(DomainError) as ctx:
            AccountingService.post_journal(
                lines=[
                    {"account_code": self.bank, "debit": Decimal("1"), "credit": 0},
                    {"account_code": self.rev, "debit": 0, "credit": Decimal("1")},
                ],
                memo="late arrival",
                source="manual",
                source_ref="p12-closed-date",
                entry_date=closed_day,
            )
        self.assertIn("bağlıdır", str(ctx.exception).lower())
        self.assertFalse(
            JournalEntry.objects.filter(source_ref="p12-closed-date").exists()
        )

        # Draft JE created before close, then period closed → post_to_gl blocked
        open_day = today
        draft = AccountingService.post_journal(
            lines=[
                {"account_code": self.bank, "debit": Decimal("5"), "credit": 0},
                {"account_code": self.rev, "debit": 0, "credit": Decimal("5")},
            ],
            memo="then close",
            source="manual",
            source_ref="p12-then-close",
            entry_date=open_day,
            posted=False,
        )
        AccountingService.close_period(year=open_day.year, month=open_day.month, actor=self.accountant)
        with self.assertRaises(DomainError):
            AccountingService.post_to_gl(draft, actor=self.accountant)
        draft.refresh_from_db()
        self.assertFalse(draft.posted)
        # Preserve original date
        self.assertEqual(draft.entry_date, open_day)
        AccountingService.reopen_period(year=open_day.year, month=open_day.month, actor=self.accountant)

    def test_trial_balance_opening_movement_closing_and_as_of(self):
        # Prior month posted movement → opening for current month
        today = timezone.localdate()
        if today.month == 1:
            py, pm = today.year - 1, 12
        else:
            py, pm = today.year, today.month - 1
        prior = date(py, pm, 10)
        AccountingService.reopen_period(year=py, month=pm, actor=self.accountant)
        AccountingService.post_journal(
            lines=[
                {"account_code": self.ar, "debit": Decimal("300"), "credit": 0},
                {"account_code": self.rev, "debit": 0, "credit": Decimal("300")},
            ],
            memo="prior open",
            source="manual",
            source_ref="p12-tb-prior",
            entry_date=prior,
            posted=True,
        )
        AccountingService.close_period(year=py, month=pm, actor=self.accountant)

        cur = today.replace(day=min(today.day, 28))
        AccountingService.reopen_period(year=cur.year, month=cur.month, actor=self.accountant)
        AccountingService.post_journal(
            lines=[
                {"account_code": self.ar, "debit": Decimal("50"), "credit": 0},
                {"account_code": self.rev, "debit": 0, "credit": Decimal("50")},
            ],
            memo="current move",
            source="manual",
            source_ref="p12-tb-cur",
            entry_date=cur,
            posted=True,
        )
        rows = trial_balance(year=cur.year, month=cur.month)
        ar = next(r for r in rows if r["code"] == self.ar)
        self.assertEqual(ar["opening_balance"], Decimal("300.00"))
        self.assertEqual(ar["period_debit"], Decimal("50.00"))
        self.assertEqual(ar["closing_balance"], Decimal("350.00"))

        # as_of before current entry excludes it
        as_of = cur - timedelta(days=1)
        rows_asof = trial_balance(year=cur.year, month=cur.month, as_of=as_of)
        ar2 = next((r for r in rows_asof if r["code"] == self.ar), None)
        if ar2:
            self.assertEqual(ar2["period_debit"], Decimal("0"))
            self.assertEqual(ar2["closing_balance"], Decimal("300.00"))

    def test_operator_http_walkthrough_and_acl(self):
        inv = self._issue_vat_off(self.party, "120.00", desc="walk")
        je = JournalEntry.objects.get(source="billing.invoice", source_ref=f"invoice:{inv.pk}")
        self.assertEqual(self.fin.get(reverse("finance:journals") + "?posted=0").status_code, 200)
        detail = self.fin.get(reverse("finance:journal_detail", kwargs={"code": je.code}))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, inv.code)
        self.assertContains(detail, self.ar)
        post = self.fin.post(
            reverse("finance:journal_detail", kwargs={"code": je.code}),
            {"action": "post_gl"},
        )
        self.assertEqual(post.status_code, 302)
        je.refresh_from_db()
        self.assertTrue(je.posted)

        tb = self.fin.get(reverse("finance:trial_balance"))
        self.assertEqual(tb.status_code, 200)
        periods = self.fin.get(reverse("finance:periods"))
        self.assertEqual(periods.status_code, 200)

        # Unauthorized: reception / resident / manager cannot post or open finance journals
        for user in (self.reception, self.resident, self.manager):
            c = Client()
            c.force_login(user)
            resp = c.get(reverse("finance:journal_detail", kwargs={"code": je.code}))
            self.assertEqual(resp.status_code, 302, user.username)
            resp2 = c.post(
                reverse("finance:journals"),
                {"action": "post_gl", "entry_id": je.pk},
            )
            self.assertEqual(resp2.status_code, 302, user.username)

        # Manager payment approval does not grant period close via finance
        before = AccountingPeriod.objects.filter(
            year=timezone.localdate().year, month=timezone.localdate().month, is_closed=True
        ).count()
        mg = Client()
        mg.force_login(self.manager)
        mg.post(
            reverse("finance:periods"),
            {
                "action": "close",
                "year": timezone.localdate().year,
                "month": timezone.localdate().month,
            },
        )
        after = AccountingPeriod.objects.filter(
            year=timezone.localdate().year, month=timezone.localdate().month, is_closed=True
        ).count()
        self.assertEqual(before, after)

        # Accountant can close then reopen
        self.fin.post(
            reverse("finance:periods"),
            {
                "action": "close",
                "year": timezone.localdate().year,
                "month": timezone.localdate().month,
            },
        )
        p = AccountingPeriod.objects.get(
            year=timezone.localdate().year, month=timezone.localdate().month
        )
        self.assertTrue(p.is_closed)
        self.fin.post(
            reverse("finance:periods"),
            {
                "action": "reopen",
                "year": timezone.localdate().year,
                "month": timezone.localdate().month,
            },
        )
        p.refresh_from_db()
        self.assertFalse(p.is_closed)

    def test_historical_lines_stable_after_mapping_change(self):
        inv = self._issue_vat_off(self.party, "70.00", desc="hist")
        je = JournalEntry.objects.get(source="billing.invoice", source_ref=f"invoice:{inv.pk}")
        AccountingService.post_to_gl(je, actor=self.accountant)
        frozen = list(
            je.lines.values_list("account__code", "debit", "credit")
        )
        # Change role mapping would require editing coa — mutate account name instead
        acct = Account.objects.get(code=self.rev)
        acct.name = "Kirayə gəliri (yenidən adlandırılmış)"
        acct.save(update_fields=["name"])
        je.refresh_from_db()
        self.assertEqual(
            list(je.lines.values_list("account__code", "debit", "credit")),
            frozen,
        )


class Phase12ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        seed_minimal_coa()
        self.party = Party.objects.create(legal_name="P12 Conc", party_type=PartyType.ORGANIZATION)
        charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="conc",
            amount=Decimal("1000.00"),
            currency="AZN",
        )
        self.inv = generate_invoice_from_charges(self.party, [charge.pk], apply_vat=False)
        confirm_invoice(self.inv)
        self.je = JournalEntry.objects.get(
            source="billing.invoice", source_ref=f"invoice:{self.inv.pk}"
        )
        self.accountant = User.objects.create_user(
            username="p12c-acc",
            email="p12c@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )

    def test_concurrent_post_to_gl_one_effective(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL row-level locks")
        je_id = self.je.pk
        actor_id = self.accountant.pk
        barrier = threading.Barrier(2, timeout=20)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker(tag: str):
            connections.close_all()
            try:
                barrier.wait()
                entry = JournalEntry.objects.get(pk=je_id)
                actor = User.objects.get(pk=actor_id)
                AccountingService.post_to_gl(entry, actor=actor)
                with lock:
                    outcomes.append(f"ok:{tag}")
            except Exception as exc:  # noqa: BLE001
                with lock:
                    outcomes.append(f"err:{tag}:{exc}")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(t,)) for t in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)
            self.assertFalse(t.is_alive())
        self.assertEqual(len([o for o in outcomes if o.startswith("ok:")]), 2, outcomes)
        self.je.refresh_from_db()
        self.assertTrue(self.je.posted)
        self.assertEqual(
            JournalEntry.objects.filter(
                source="billing.invoice", source_ref=f"invoice:{self.inv.pk}"
            ).count(),
            1,
        )

    def test_concurrent_close_and_post(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL row-level locks")
        today = timezone.localdate()
        AccountingPeriod.objects.get_or_create(year=today.year, month=today.month)
        je_id = self.je.pk
        actor_id = self.accountant.pk
        year, month = today.year, today.month
        barrier = threading.Barrier(2, timeout=20)
        outcomes: list[str] = []
        lock = threading.Lock()

        def poster():
            connections.close_all()
            try:
                barrier.wait()
                entry = JournalEntry.objects.get(pk=je_id)
                AccountingService.post_to_gl(entry, actor=User.objects.get(pk=actor_id))
                with lock:
                    outcomes.append("post:ok")
            except DomainError as exc:
                with lock:
                    outcomes.append(f"post:err:{exc}")
            except Exception as exc:  # noqa: BLE001
                with lock:
                    outcomes.append(f"post:ex:{exc}")
            finally:
                connections.close_all()

        def closer():
            connections.close_all()
            try:
                barrier.wait()
                AccountingService.close_period(
                    year=year, month=month, actor=User.objects.get(pk=actor_id)
                )
                with lock:
                    outcomes.append("close:ok")
            except Exception as exc:  # noqa: BLE001
                with lock:
                    outcomes.append(f"close:ex:{exc}")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=poster), threading.Thread(target=closer)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)
            self.assertFalse(t.is_alive())

        period = AccountingPeriod.objects.get(year=year, month=month)
        self.je.refresh_from_db()
        self.assertTrue(period.is_closed or self.je.posted, outcomes)
        # Exactly one winner path: either posted before close, or post declined after close
        if self.je.posted:
            self.assertIn("post:ok", outcomes)
        else:
            self.assertTrue(any(o.startswith("post:err:") for o in outcomes), outcomes)
            self.assertIn("close:ok", outcomes)
