from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.comms.announcements import announcements_for_user
from apps.comms.models import Announcement, AnnouncementVisibility
from apps.residents.models import ResidentCompany

User = get_user_model()


class PortalActiveGateTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(
            name="Pilot Co",
            slug="pilot-co",
            portal_active=True,
        )
        self.user = User.objects.create_user(
            username="pilot",
            email="pilot@example.com",
            password="test-pass-123",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        self.client = Client()

    def test_portal_ok_when_active(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("portal:home"))
        self.assertEqual(r.status_code, 200)

    def test_portal_denied_when_inactive(self):
        self.company.portal_active = False
        self.company.save(update_fields=["portal_active"])
        self.client.force_login(self.user)
        r = self.client.get(reverse("portal:home"))
        self.assertEqual(r.status_code, 403)


class AnnouncementScopeTests(TestCase):
    def setUp(self):
        self.c1 = ResidentCompany.objects.create(name="A", slug="a-co")
        self.c2 = ResidentCompany.objects.create(name="B", slug="b-co")
        self.u1 = User.objects.create_user(
            username="a1",
            email="a1@example.com",
            password="test-pass-123",
            role=Role.RESIDENT_USER,
            resident_company=self.c1,
        )
        self.u2 = User.objects.create_user(
            username="b1",
            email="b1@example.com",
            password="test-pass-123",
            role=Role.RESIDENT_USER,
            resident_company=self.c2,
        )
        today = timezone.localdate()
        self.building = Announcement.objects.create(
            title="Building",
            body="all",
            published_at=today,
            visibility=AnnouncementVisibility.BUILDING,
        )
        self.for_a = Announcement.objects.create(
            title="Only A",
            body="secret",
            published_at=today,
            visibility=AnnouncementVisibility.COMPANY,
            company=self.c1,
        )
        self.for_b = Announcement.objects.create(
            title="Only B",
            body="secret",
            published_at=today,
            visibility=AnnouncementVisibility.COMPANY,
            company=self.c2,
        )
        self.targeted = Announcement.objects.create(
            title="Target u1",
            body="hi",
            published_at=today,
            visibility=AnnouncementVisibility.TARGETED,
            company=self.c1,
        )
        self.targeted.target_users.add(self.u1)

    def test_company_isolation(self):
        titles_a = set(announcements_for_user(self.u1).values_list("title", flat=True))
        titles_b = set(announcements_for_user(self.u2).values_list("title", flat=True))
        self.assertIn("Building", titles_a)
        self.assertIn("Only A", titles_a)
        self.assertIn("Target u1", titles_a)
        self.assertNotIn("Only B", titles_a)
        self.assertIn("Only B", titles_b)
        self.assertNotIn("Only A", titles_b)
        self.assertNotIn("Target u1", titles_b)
