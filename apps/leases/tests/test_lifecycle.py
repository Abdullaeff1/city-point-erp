from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.leases.models import Lease, LeaseStatus
from apps.leases.services import process_lease_lifecycle
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
        stats = process_lease_lifecycle(as_of=today, expiring_days=30)
        self.assertEqual(stats["marked_expiring"], 1)
        lease.refresh_from_db()
        self.space.refresh_from_db()
        self.assertEqual(lease.status, LeaseStatus.EXPIRING)
        self.assertEqual(self.space.commercial_status, CommercialStatus.NOTICE)
