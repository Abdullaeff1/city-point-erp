from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.accounts.object_scope import accessible_company_ids_for, party_accessible
from apps.accounts.test_utils import ensure_portal_membership, ensure_portal_memberships
from apps.parties.services import PartyService
from apps.rbac.services import seed_rbac_catalog, user_has_permission
from apps.residents.models import ResidentCompany
from apps.residents.permissions import user_can_access_portal_document_in_scope
from apps.tickets.access import can_access_ticket_attachment, can_delete_ticket
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import create_ticket_from_portal

User = get_user_model()


class ObjectScopeTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.co_a = ResidentCompany.objects.create(
            name="Scope A", slug="scope-a", portal_active=True, is_internal=False
        )
        self.co_b = ResidentCompany.objects.create(
            name="Scope B", slug="scope-b", portal_active=True, is_internal=False
        )
        self.party_a = PartyService.upsert_from_resident_company(self.co_a, audit=False)
        self.user = User.objects.create_user(
            username="res-scope",
            email="res-scope@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_memberships(self.user, [self.co_a, self.co_b], primary_company=self.co_a)

    def test_accessible_includes_all_memberships(self):
        ids = accessible_company_ids_for(self.user)
        self.assertEqual(ids, {self.co_a.pk, self.co_b.pk})

    def test_party_accessible_matches_company(self):
        self.assertTrue(party_accessible(self.user, self.party_a))
        party_b = PartyService.upsert_from_resident_company(self.co_b, audit=False)
        self.assertTrue(party_accessible(self.user, party_b))
        # Session narrowed to A only
        self.assertTrue(party_accessible(self.user, self.party_a, company_ids=[self.co_a.pk]))
        self.assertFalse(party_accessible(self.user, party_b, company_ids=[self.co_a.pk]))

    def test_ticket_attachment_secondary_membership(self):
        seed_ticket_taxonomy()
        from apps.tickets.models import TicketSubcategory

        sub = TicketSubcategory.objects.filter(is_active=True).first()
        ticket_b = create_ticket_from_portal(
            company=self.co_b,
            requester=self.user,
            ticket_type="incident",
            category=sub.category,
            subcategory=sub,
            description="Secondary company ticket",
        )
        # Primary FK is co_a; old bug would deny co_b
        self.assertNotEqual(self.user.resident_company_id, self.co_b.pk)
        self.assertTrue(can_access_ticket_attachment(self.user, ticket_b))
        self.assertTrue(can_delete_ticket(self.user, ticket_b))

        outsider = User.objects.create_user(
            username="out",
            email="out@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_membership(outsider, self.co_a)
        self.assertFalse(can_access_ticket_attachment(outsider, ticket_b))

    def test_document_staff_respects_scope_ids(self):
        from django.utils import timezone

        from apps.documents.models import Document, DocumentType

        dtype, _ = DocumentType.objects.get_or_create(code="other", defaults={"name": "Other"})
        doc = Document.objects.create(
            company=self.co_b,
            document_type=dtype,
            title="B doc",
            visible_to_resident=True,
            published_at=timezone.localdate(),
        )
        fm = User.objects.create_user(
            username="fm-scope",
            email="fm-scope@test.az",
            password="Pass12345!",
            role=Role.SERVICE_DESK,
        )
        self.assertTrue(user_can_access_portal_document_in_scope(fm, doc, [self.co_b.pk]))
        self.assertFalse(user_can_access_portal_document_in_scope(fm, doc, [self.co_a.pk]))

    def test_rbac_sales_and_announcement_a8(self):
        sales = User.objects.create_user(
            username="sales1",
            email="sales1@test.az",
            password="Pass12345!",
            role=Role.SALES,
        )
        self.assertTrue(user_has_permission(sales, "lease.view"))
        self.assertTrue(user_has_permission(sales, "lease.edit"))
        mgmt = User.objects.create_user(
            username="mgmt-a8",
            email="mgmt-a8@test.az",
            password="Pass12345!",
            role=Role.MANAGEMENT,
        )
        self.assertTrue(user_has_permission(mgmt, "lease.view"))
        self.assertFalse(user_has_permission(mgmt, "announcement.publish"))

    def test_lease_edit_requires_permission(self):
        from apps.leases.models import Lease, LeaseStatus
        from apps.property.models import Building, Floor, Space

        building = Building.objects.create(name="B1", code="b1-m2")
        floor = Floor.objects.create(building=building, code="1", name="1")
        space = Space.objects.create(floor=floor, code="S-M2")
        lease = Lease.objects.create(
            code="L-M2-1",
            party=self.party_a,
            space=space,
            status=LeaseStatus.SIGNED,
        )
        # handler403 redirects denied staff home (302), not raw 403 body
        reception = User.objects.create_user(
            username="rec-m2",
            email="rec-m2@test.az",
            password="Pass12345!",
            role=Role.RECEPTION,
        )
        client = Client()
        client.force_login(reception)
        resp = client.get(reverse("erp:lease_detail", kwargs={"code": lease.code}))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(user_has_permission(reception, "lease.view"))

        desk = User.objects.create_user(
            username="desk-m2",
            email="desk-m2@test.az",
            password="Pass12345!",
            role=Role.SERVICE_DESK,
        )
        client.force_login(desk)
        resp = client.get(reverse("erp:lease_detail", kwargs={"code": lease.code}))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["can_edit_lease"])
        self.assertFalse(user_has_permission(desk, "lease.edit"))
        client.post(
            reverse("erp:lease_detail", kwargs={"code": lease.code}),
            {"action": "activate"},
        )
        lease.refresh_from_db()
        self.assertEqual(lease.status, LeaseStatus.SIGNED)

        fm = User.objects.create_user(
            username="fm-m2",
            email="fm-m2@test.az",
            password="Pass12345!",
            role=Role.SERVICE_DESK,
        )
        client.force_login(fm)
        resp = client.get(reverse("erp:lease_detail", kwargs={"code": lease.code}))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["can_edit_lease"])
