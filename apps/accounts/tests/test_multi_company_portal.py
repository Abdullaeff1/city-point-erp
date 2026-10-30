from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.membership import deactivate_membership, set_user_memberships
from apps.accounts.models import PortalCompanyMembership, Role
from apps.accounts.portal_scope import MODE_ALL, MODE_SINGLE, eligible_companies_for
from apps.accounts.test_utils import ensure_portal_membership, ensure_portal_memberships
from apps.property.models import Building, Floor, Space
from apps.residents.models import CompanyStatus, ResidentCompany
from apps.tickets.models import Ticket, TicketSubcategory
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import create_ticket_from_portal

User = get_user_model()


class MultiCompanyLoginTests(TestCase):
    def setUp(self):
        self.c1 = ResidentCompany.objects.create(name="Tvins", slug="tvins", portal_active=True)
        self.c2 = ResidentCompany.objects.create(name="Park Elmlər", slug="park-elmler", portal_active=True)
        self.client = Client()

    def test_zero_membership_rejected(self):
        user = User.objects.create_user(
            username="zero",
            email="zero@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        logged = self.client.login(username="zero@test.az", password="Pass12345!")
        self.assertTrue(logged)
        resp = self.client.get(reverse("post_login"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp["Location"])
        # session cleared
        resp2 = self.client.get(reverse("portal:home"))
        self.assertEqual(resp2.status_code, 302)

    def test_one_company_goes_home(self):
        user = User.objects.create_user(
            username="one",
            email="one@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_membership(user, self.c1)
        self.client.login(username="one@test.az", password="Pass12345!")
        resp = self.client.get(reverse("post_login"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("portal:home"))
        home = self.client.get(reverse("portal:home"))
        self.assertEqual(home.status_code, 200)
        self.assertEqual(self.client.session.get("portal_scope_mode"), MODE_SINGLE)

    def test_two_companies_chooser(self):
        user = User.objects.create_user(
            username="two",
            email="two@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_memberships(user, [self.c1, self.c2])
        self.client.login(username="two@test.az", password="Pass12345!")
        resp = self.client.get(reverse("post_login"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("portal:choose_companies"))
        # home redirects to chooser without scope
        home = self.client.get(reverse("portal:home"))
        self.assertEqual(home.status_code, 302)
        self.assertEqual(home["Location"], reverse("portal:choose_companies"))

    def test_choose_single_post(self):
        user = User.objects.create_user(
            username="pick",
            email="pick@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_memberships(user, [self.c1, self.c2])
        self.client.login(username="pick@test.az", password="Pass12345!")
        resp = self.client.post(reverse("portal:choose_companies"), {"choice": str(self.c1.pk)})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("portal:home"))
        self.assertEqual(self.client.session["portal_scope_mode"], MODE_SINGLE)
        self.assertEqual(self.client.session["portal_company_ids"], [self.c1.pk])

    def test_choose_all_post(self):
        user = User.objects.create_user(
            username="allu",
            email="allu@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_memberships(user, [self.c1, self.c2])
        self.client.login(username="allu@test.az", password="Pass12345!")
        resp = self.client.post(reverse("portal:choose_companies"), {"choice": "all"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.session["portal_scope_mode"], MODE_ALL)
        self.assertEqual(set(self.client.session["portal_company_ids"]), {self.c1.pk, self.c2.pk})

    def test_cannot_post_foreign_company(self):
        foreign = ResidentCompany.objects.create(name="Foreign", slug="foreign-x", portal_active=True)
        user = User.objects.create_user(
            username="nope",
            email="nope@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_memberships(user, [self.c1, self.c2])
        self.client.login(username="nope@test.az", password="Pass12345!")
        resp = self.client.post(reverse("portal:choose_companies"), {"choice": str(foreign.pk)})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(self.client.session.get("portal_scope_mode"))

    def test_staff_login_unchanged(self):
        User.objects.create_user(
            username="adm",
            email="adm@test.az",
            password="Pass12345!",
            role=Role.ADMIN,
        )
        self.client.login(username="adm@test.az", password="Pass12345!")
        resp = self.client.get(reverse("post_login"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("erp:dashboard"))


class EligibilityAndSessionTests(TestCase):
    def setUp(self):
        self.c1 = ResidentCompany.objects.create(name="A", slug="elig-a", portal_active=True)
        self.c2 = ResidentCompany.objects.create(name="B", slug="elig-b", portal_active=True)
        self.user = User.objects.create_user(
            username="elig",
            email="elig@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_memberships(self.user, [self.c1, self.c2])
        self.client = Client()
        self.client.login(username="elig@test.az", password="Pass12345!")
        self.client.post(reverse("portal:choose_companies"), {"choice": "all"})

    def test_portal_active_false_hidden(self):
        self.c2.portal_active = False
        self.c2.save(update_fields=["portal_active"])
        names = [c.name for c in eligible_companies_for(self.user)]
        self.assertEqual(names, ["A"])
        # existing all-scope revalidated on next request
        resp = self.client.get(reverse("portal:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.session["portal_company_ids"], [self.c1.pk])

    def test_inactive_status_hidden(self):
        self.c2.status = CompanyStatus.INACTIVE
        self.c2.save(update_fields=["status"])
        self.assertEqual([c.pk for c in eligible_companies_for(self.user)], [self.c1.pk])

    def test_internal_hidden(self):
        self.c2.is_internal = True
        self.c2.save(update_fields=["is_internal"])
        self.assertEqual([c.pk for c in eligible_companies_for(self.user)], [self.c1.pk])

    def test_membership_deactivate_revokes_session(self):
        deactivate_membership(user=self.user, company=self.c1)
        deactivate_membership(user=self.user, company=self.c2)
        resp = self.client.get(reverse("portal:home"))
        self.assertEqual(resp.status_code, 403)

    def test_switch_clears_previous_scope(self):
        self.assertEqual(self.client.session["portal_scope_mode"], MODE_ALL)
        self.client.get(reverse("portal:choose_companies"))
        self.assertIsNone(self.client.session.get("portal_scope_mode"))
        home = self.client.get(reverse("portal:home"))
        self.assertEqual(home.status_code, 302)
        self.assertEqual(home["Location"], reverse("portal:choose_companies"))

    def test_logout_clears_scope(self):
        self.client.post(reverse("logout"))
        self.assertIsNone(self.client.session.get("portal_scope_mode"))


class IsolationAndCreateTests(TestCase):
    def setUp(self):
        seed_ticket_taxonomy()
        self.c1 = ResidentCompany.objects.create(name="Tvins", slug="iso-tvins", portal_active=True)
        self.c2 = ResidentCompany.objects.create(name="Park", slug="iso-park", portal_active=True)
        building = Building.objects.create(code="CP", name="City Point")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        self.space1 = Space.objects.create(
            code="CP-F01-OFF-1", name="1", floor=floor, resident=self.c1, area_m2="10"
        )
        self.space2 = Space.objects.create(
            code="CP-F01-OFF-2", name="2", floor=floor, resident=self.c2, area_m2="10"
        )
        self.user = User.objects.create_user(
            username="iso",
            email="iso@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_memberships(self.user, [self.c1, self.c2])
        self.client = Client()
        self.client.login(username="iso@test.az", password="Pass12345!")

        sub = TicketSubcategory.objects.filter(is_active=True).first()
        self.t1 = create_ticket_from_portal(
            company=self.c1,
            requester=self.user,
            ticket_type="incident",
            category=sub.category,
            subcategory=sub,
            description="c1 ticket",
            space=self.space1,
        )
        self.t2 = create_ticket_from_portal(
            company=self.c2,
            requester=self.user,
            ticket_type="incident",
            category=sub.category,
            subcategory=sub,
            description="c2 ticket",
            space=self.space2,
        )

    def test_single_scope_isolates(self):
        self.client.post(reverse("portal:choose_companies"), {"choice": str(self.c1.pk)})
        resp = self.client.get(reverse("portal:requests_active"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.t1.code)
        self.assertNotContains(resp, self.t2.code)
        detail = self.client.get(reverse("portal:request_detail", args=[self.t2.code]))
        self.assertEqual(detail.status_code, 404)
        space = self.client.get(reverse("portal:space_detail", args=[self.space2.code]))
        self.assertEqual(space.status_code, 404)

    def test_all_scope_shows_both(self):
        self.client.post(reverse("portal:choose_companies"), {"choice": "all"})
        resp = self.client.get(reverse("portal:requests_active"))
        self.assertContains(resp, self.t1.code)
        self.assertContains(resp, self.t2.code)
        self.assertContains(resp, "Tvins")
        self.assertContains(resp, "Park")

    def test_create_all_requires_company(self):
        self.client.post(reverse("portal:choose_companies"), {"choice": "all"})
        sub = TicketSubcategory.objects.filter(is_active=True).first()
        resp = self.client.post(
            reverse("portal:request_new"),
            {
                "ticket_type": "incident",
                "category": sub.category_id,
                "subcategory": sub.pk,
                "description": "no company",
                "space": "",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Ticket.objects.filter(description="no company").exists())

    def test_create_all_with_allowed_company(self):
        self.client.post(reverse("portal:choose_companies"), {"choice": "all"})
        sub = TicketSubcategory.objects.filter(is_active=True).first()
        resp = self.client.post(
            reverse("portal:request_new"),
            {
                "company": self.c2.pk,
                "ticket_type": "incident",
                "category": sub.category_id,
                "subcategory": sub.pk,
                "description": "park ticket",
                "space": self.space2.pk,
            },
        )
        self.assertEqual(resp.status_code, 302)
        ticket = Ticket.objects.get(description="park ticket")
        self.assertEqual(ticket.company_id, self.c2.pk)

    def test_create_rejects_foreign_company_id(self):
        foreign = ResidentCompany.objects.create(name="X", slug="iso-x", portal_active=True)
        self.client.post(reverse("portal:choose_companies"), {"choice": "all"})
        sub = TicketSubcategory.objects.filter(is_active=True).first()
        resp = self.client.post(
            reverse("portal:request_new"),
            {
                "company": foreign.pk,
                "ticket_type": "incident",
                "category": sub.category_id,
                "subcategory": sub.pk,
                "description": "hack",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Ticket.objects.filter(description="hack").exists())

    def test_single_create_uses_scope_company(self):
        self.client.post(reverse("portal:choose_companies"), {"choice": str(self.c1.pk)})
        sub = TicketSubcategory.objects.filter(is_active=True).first()
        resp = self.client.post(
            reverse("portal:request_new"),
            {
                "ticket_type": "incident",
                "category": sub.category_id,
                "subcategory": sub.pk,
                "description": "auto company",
                "space": self.space1.pk,
            },
        )
        self.assertEqual(resp.status_code, 302)
        ticket = Ticket.objects.get(description="auto company")
        self.assertEqual(ticket.company_id, self.c1.pk)


class BackfillMembershipTests(TestCase):
    def test_set_user_memberships_syncs_fk(self):
        c1 = ResidentCompany.objects.create(name="M1", slug="m1", portal_active=True)
        c2 = ResidentCompany.objects.create(name="M2", slug="m2", portal_active=True)
        user = User.objects.create_user(
            username="bf",
            email="bf@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        set_user_memberships(user=user, company_ids=[c1.pk, c2.pk], primary_company_id=c2.pk)
        user.refresh_from_db()
        self.assertEqual(user.resident_company_id, c2.pk)
        self.assertEqual(PortalCompanyMembership.objects.filter(user=user, is_active=True).count(), 2)
        self.assertTrue(
            PortalCompanyMembership.objects.filter(user=user, company=c2, is_primary=True).exists()
        )
