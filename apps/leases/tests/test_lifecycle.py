from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.leases.models import Lease, LeaseLine, LeaseStatus
from apps.leases.services import (
    activate_lease,
    ensure_primary_lease_line,
    process_lease_lifecycle,
    terminate_lease,
)
from apps.parties.models import Party, PartyStatus, PartyType
from apps.property.models import Building, CommercialStatus, Floor, Occupancy, Space
from apps.residents.models import ResidentCompany

User = get_user_model()


class LeaseLifecycleTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(
            name="LifeCo", slug="lifeco-test", portal_active=False, is_internal=False
        )
        self.party = Party.objects.create(
            party_type=PartyType.ORGANIZATION,
            legal_name="LifeCo LLC",
            status=PartyStatus.PROSPECT,
            legacy_resident_company=self.company,
        )
        building = Building.objects.create(name="B", code="BLC")
        floor = Floor.objects.create(building=building, code="1", name="1")
        self.space = Space.objects.create(
            floor=floor,
            code="S-LC",
            commercial_status=CommercialStatus.CONTRACTED,
            occupancy=Occupancy.VACANT,
            area_m2=100,
        )
        self.space_b = Space.objects.create(
            floor=floor,
            code="S-LC-B",
            commercial_status=CommercialStatus.VACANT,
            occupancy=Occupancy.VACANT,
            area_m2=50,
        )
        User.objects.create_user(
            username="sales1",
            email="sales@test.az",
            password="Pass12345!",
            role=Role.SALES,
        )

    def test_signed_activates_on_start_date(self):
        today = timezone.localdate()
        lease = Lease.objects.create(
            code="LS-9001",
            party=self.party,
            space=self.space,
            status=LeaseStatus.SIGNED,
            start_date=today,
            end_date=today + timedelta(days=365),
        )
        stats = process_lease_lifecycle(as_of=today, expiring_days=90)
        self.assertEqual(stats["activated"], 1)
        lease.refresh_from_db()
        self.space.refresh_from_db()
        self.company.refresh_from_db()
        self.assertEqual(lease.status, LeaseStatus.ACTIVE)
        self.assertTrue(lease.billing_active)
        self.assertEqual(self.space.occupancy, Occupancy.ACTIVE_LEASE)
        self.assertEqual(self.space.resident_id, self.company.pk)
        self.assertTrue(self.company.portal_active)
        self.assertTrue(LeaseLine.objects.filter(lease=lease, space=self.space).exists())

    def test_active_marked_expiring_in_window(self):
        today = timezone.localdate()
        lease = Lease.objects.create(
            code="LS-9002",
            party=self.party,
            space=self.space,
            status=LeaseStatus.ACTIVE,
            billing_active=True,
            portal_eligible=True,
            access_eligible=True,
            start_date=today - timedelta(days=300),
            end_date=today + timedelta(days=10),
        )
        ensure_primary_lease_line(lease)
        stats = process_lease_lifecycle(as_of=today, expiring_days=30)
        self.assertEqual(stats["marked_expiring"], 1)
        lease.refresh_from_db()
        self.space.refresh_from_db()
        self.assertEqual(lease.status, LeaseStatus.EXPIRING)
        self.assertEqual(self.space.commercial_status, CommercialStatus.NOTICE)

    def test_terminate_clears_bridge_and_portal(self):
        lease = Lease.objects.create(
            code="LS-9003",
            party=self.party,
            space=self.space,
            status=LeaseStatus.SIGNED,
            start_date=timezone.localdate(),
        )
        activate_lease(lease)
        self.space.refresh_from_db()
        self.company.refresh_from_db()
        self.assertEqual(self.space.resident_id, self.company.pk)
        self.assertTrue(self.company.portal_active)

        terminate_lease(lease)
        self.space.refresh_from_db()
        self.company.refresh_from_db()
        lease.refresh_from_db()
        self.assertEqual(lease.status, LeaseStatus.TERMINATED)
        self.assertFalse(lease.portal_eligible)
        self.assertEqual(self.space.occupancy, Occupancy.VACANT)
        self.assertIsNone(self.space.resident_id)
        self.assertEqual(self.space.commercial_status, CommercialStatus.VACANT)
        self.assertFalse(self.company.portal_active)

    def test_multi_line_activate_and_terminate(self):
        lease = Lease.objects.create(
            code="LS-9004",
            party=self.party,
            space=self.space,
            status=LeaseStatus.SIGNED,
            start_date=timezone.localdate(),
        )
        ensure_primary_lease_line(lease)
        LeaseLine.objects.create(lease=lease, space=self.space_b, area_m2=50)

        activate_lease(lease)
        self.space.refresh_from_db()
        self.space_b.refresh_from_db()
        self.assertEqual(self.space.occupancy, Occupancy.ACTIVE_LEASE)
        self.assertEqual(self.space_b.occupancy, Occupancy.ACTIVE_LEASE)
        self.assertEqual(self.space_b.resident_id, self.company.pk)
        self.assertEqual(self.space_b.commercial_status, CommercialStatus.ACTIVE)

        terminate_lease(lease)
        self.space.refresh_from_db()
        self.space_b.refresh_from_db()
        self.assertEqual(self.space.occupancy, Occupancy.VACANT)
        self.assertEqual(self.space_b.occupancy, Occupancy.VACANT)
        self.assertIsNone(self.space.resident_id)
        self.assertIsNone(self.space_b.resident_id)

    def test_terminate_keeps_portal_if_other_open_lease(self):
        first = Lease.objects.create(
            code="LS-9005",
            party=self.party,
            space=self.space,
            status=LeaseStatus.SIGNED,
            start_date=timezone.localdate(),
        )
        second = Lease.objects.create(
            code="LS-9006",
            party=self.party,
            space=self.space_b,
            status=LeaseStatus.SIGNED,
            start_date=timezone.localdate(),
        )
        activate_lease(first)
        activate_lease(second)
        self.company.refresh_from_db()
        self.assertTrue(self.company.portal_active)

        terminate_lease(first)
        self.company.refresh_from_db()
        self.assertTrue(self.company.portal_active)
        self.space.refresh_from_db()
        self.assertIsNone(self.space.resident_id)

        terminate_lease(second)
        self.company.refresh_from_db()
        self.assertFalse(self.company.portal_active)
