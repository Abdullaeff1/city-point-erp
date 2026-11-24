from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.billing.models import Charge, ChargeSource
from apps.billing.services import confirm_invoice, generate_invoice_from_charges
from apps.core.models import ReportSnapshot
from apps.erp.exec_reports import (
    build_exec_bundle,
    build_finance_report,
    build_property_report,
    capture_daily_snapshot,
    parse_report_params,
)
from apps.parties.models import Party, PartyStatus, PartyType
from apps.property.models import Building, CommercialStatus, Floor, Occupancy, Space

User = get_user_model()


class ExecReportBuildersTests(TestCase):
    def setUp(self):
        from apps.leases.models import Lease, LeaseStatus

        self.party = Party.objects.create(
            party_type=PartyType.ORGANIZATION,
            legal_name="M11 Co",
            status=PartyStatus.ACTIVE,
        )
        building = Building.objects.create(code="M11B", name="M11B")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        self.s1 = Space.objects.create(
            code="M11-S1",
            name="S1",
            floor=floor,
            area_m2=Decimal("100"),
            rentable_area_m2=Decimal("100"),
            commercial_status=CommercialStatus.VACANT,
            occupancy=Occupancy.VACANT,
        )
        self.s2 = Space.objects.create(
            code="M11-S2",
            name="S2",
            floor=floor,
            area_m2=Decimal("100"),
            rentable_area_m2=Decimal("100"),
            commercial_status=CommercialStatus.ACTIVE,
            occupancy=Occupancy.ACTIVE_LEASE,
        )
        lease = Lease.objects.create(
            code="LS-M11-S2",
            party=self.party,
            space=self.s2,
            status=LeaseStatus.ACTIVE,
            start_date=timezone.localdate().replace(year=2026, month=1, day=1),
            rent=Decimal("1000"),
        )
        # Hold must be recorded on/before as_of used in assertions (2026-11-18)
        Lease.objects.filter(pk=lease.pk).update(
            created_at=timezone.make_aware(datetime(2026, 1, 1, 9, 0, 0))
        )

    def test_parse_params_and_property(self):
        params = parse_report_params({"date_from": "2026-11-01", "date_to": "2026-11-18"})
        self.assertEqual(params["date_from"].isoformat(), "2026-11-01")
        prop = build_property_report(params)
        self.assertEqual(prop["space_count"], 2)
        self.assertEqual(prop["available_count"], 1)
        self.assertEqual(prop["occupied_count"], 1)
        self.assertAlmostEqual(prop["occupancy_pct"], 50.0)

    def test_finance_and_snapshot(self):
        charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="M11 rent",
            amount=Decimal("100.00"),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(self.party, [charge.pk], apply_vat=False)
        confirm_invoice(inv)
        today = timezone.localdate()
        params = {"date_from": today - timedelta(days=5), "date_to": today, "company_id": None}
        fin = build_finance_report(params)
        self.assertGreaterEqual(fin["invoiced"], Decimal("100.00"))
        snap = capture_daily_snapshot(as_of=today)
        self.assertTrue(ReportSnapshot.objects.filter(pk=snap.pk).exists())
        self.assertIn("finance", snap.payload)
        # idempotent same day
        snap2 = capture_daily_snapshot(as_of=today)
        self.assertEqual(snap.pk, snap2.pk)

    def test_bundle_keys(self):
        params = parse_report_params({})
        bundle = build_exec_bundle(params)
        for key in ("property", "crm", "sales", "fm", "warehouse", "finance", "security", "service_desk"):
            self.assertIn(key, bundle)


class ExecReportsAclTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="m11-mgr",
            email="m11-mgr@test.az",
            password="Pass12345!",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.reception = User.objects.create_user(
            username="m11-rec",
            email="m11-rec@test.az",
            password="Pass12345!",
            role=Role.RECEPTION,
            is_staff=True,
        )
        self.client = Client()

    def test_manager_reports_ok_reception_denied(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("erp:reports"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Doluluq")
        export = self.client.get(reverse("erp:reports_export"))
        self.assertEqual(export.status_code, 200)
        self.assertIn(
            "spreadsheetml",
            export["Content-Type"],
        )
        self.client.force_login(self.reception)
        denied = self.client.get(reverse("erp:reports"))
        self.assertIn(denied.status_code, (302, 403))
