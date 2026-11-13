"""A.8 — announcement visibility, Admin-first publish, multi-company."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.comms.announcements import announcements_for_user, can_publish_announcement
from apps.comms.models import Announcement, AnnouncementVisibility
from apps.rbac.models import PermissionCode, RolePermission
from apps.residents.models import ResidentCompany

User = get_user_model()


class AnnouncementVisibilityTests(TestCase):
    def setUp(self):
        self.c1 = ResidentCompany.objects.create(name="Alpha Co", slug="alpha-co")
        self.c2 = ResidentCompany.objects.create(name="Beta Co", slug="beta-co")
        self.c3 = ResidentCompany.objects.create(name="Gamma Co", slug="gamma-co")
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
        self.single = Announcement.objects.create(
            title="Only A",
            body="a",
            published_at=today,
            visibility=AnnouncementVisibility.COMPANY,
            company=self.c1,
        )
        self.single.companies.add(self.c1)
        self.multi = Announcement.objects.create(
            title="A and B",
            body="ab",
            published_at=today,
            visibility=AnnouncementVisibility.COMPANY,
        )
        self.multi.companies.set([self.c1, self.c2])
        self.only_c = Announcement.objects.create(
            title="Only C",
            body="c",
            published_at=today,
            visibility=AnnouncementVisibility.COMPANY,
        )
        self.only_c.companies.add(self.c3)

    def test_building_visible_to_all(self):
        self.assertIn(self.building, announcements_for_user(self.u1))
        self.assertIn(self.building, announcements_for_user(self.u2))

    def test_single_company(self):
        titles_a = set(announcements_for_user(self.u1).values_list("title", flat=True))
        titles_b = set(announcements_for_user(self.u2).values_list("title", flat=True))
        self.assertIn("Only A", titles_a)
        self.assertNotIn("Only A", titles_b)

    def test_multi_company_overlap(self):
        titles_a = set(announcements_for_user(self.u1).values_list("title", flat=True))
        titles_b = set(announcements_for_user(self.u2).values_list("title", flat=True))
        self.assertIn("A and B", titles_a)
        self.assertIn("A and B", titles_b)
        self.assertNotIn("Only C", titles_a)
        self.assertNotIn("Only C", titles_b)

    def test_portal_company_ids_scope(self):
        qs = announcements_for_user(self.u1, company_ids=[self.c1.pk, self.c3.pk])
        titles = set(qs.values_list("title", flat=True))
        self.assertIn("Only A", titles)
        self.assertIn("Only C", titles)
        self.assertIn("A and B", titles)


class AnnouncementPublishPermissionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin1",
            email="admin@example.com",
            password="test-pass-123",
            role=Role.ADMIN,
        )
        self.mgmt = User.objects.create_user(
            username="mgmt1",
            email="mgmt@example.com",
            password="test-pass-123",
            role=Role.MANAGEMENT,
        )
        self.desk = User.objects.create_user(
            username="desk1",
            email="desk@example.com",
            password="test-pass-123",
            role=Role.SERVICE_DESK,
        )

    def test_admin_can_publish(self):
        self.assertTrue(can_publish_announcement(self.admin))

    def test_management_cannot_without_rbac(self):
        self.assertFalse(can_publish_announcement(self.mgmt))

    def test_service_desk_cannot(self):
        self.assertFalse(can_publish_announcement(self.desk))

    def test_rbac_grant_enables_staff(self):
        perm, _ = PermissionCode.objects.get_or_create(
            code="announcement.publish",
            defaults={"name": "Elan nəşri", "module": "comms"},
        )
        RolePermission.objects.get_or_create(role=Role.SERVICE_DESK, permission=perm)
        self.assertTrue(can_publish_announcement(self.desk))

    def test_erp_create_admin_ok_others_403(self):
        url = reverse("erp:announcement_create")
        self.client.force_login(self.admin)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        self.client.force_login(self.desk)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

        self.client.force_login(self.mgmt)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_create_multi_company(self):
        c1 = ResidentCompany.objects.create(name="X", slug="x-co")
        c2 = ResidentCompany.objects.create(name="Y", slug="y-co")
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("erp:announcement_create"),
            {
                "title": "Multi",
                "body": "Hello",
                "severity": "info",
                "published_at": timezone.localdate().isoformat(),
                "visibility": AnnouncementVisibility.COMPANY,
                "companies": [c1.pk, c2.pk],
            },
        )
        self.assertEqual(resp.status_code, 302)
        ann = Announcement.objects.get(title="Multi")
        self.assertEqual(ann.visibility, AnnouncementVisibility.COMPANY)
        self.assertEqual(set(ann.companies.values_list("pk", flat=True)), {c1.pk, c2.pk})
        self.assertEqual(ann.company_id, min(c1.pk, c2.pk))

    def test_admin_can_edit_and_delete(self):
        ann = Announcement.objects.create(
            title="Old",
            body="body",
            published_at=timezone.localdate(),
            visibility=AnnouncementVisibility.BUILDING,
        )
        self.client.force_login(self.admin)
        edit_url = reverse("erp:announcement_edit", kwargs={"pk": ann.pk})
        self.assertEqual(self.client.get(edit_url).status_code, 200)
        resp = self.client.post(
            edit_url,
            {
                "title": "Updated",
                "body": "new body",
                "severity": "important",
                "published_at": timezone.localdate().isoformat(),
                "visibility": AnnouncementVisibility.BUILDING,
                "companies": [],
            },
        )
        self.assertEqual(resp.status_code, 302)
        ann.refresh_from_db()
        self.assertEqual(ann.title, "Updated")

        del_resp = self.client.post(reverse("erp:announcement_delete", kwargs={"pk": ann.pk}))
        self.assertEqual(del_resp.status_code, 302)
        self.assertFalse(Announcement.objects.filter(pk=ann.pk).exists())
