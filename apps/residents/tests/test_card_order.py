from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.integrations.axtrax_people_sync import _find_unlinked_employee_by_name
from apps.integrations.models import ExternalIdentity, SyncStatus
from apps.property.models import Building, Floor, Space
from apps.residents.card_order import (
    mark_card_order_issued_from_axtrax,
    set_card_order_status,
)
from apps.residents.models import CardOrderStatus, ResidentCompany, ResidentEmployee
from apps.residents.services import create_employee_card_order
from apps.tickets.models import Ticket, TicketStatus, TicketType
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy

User = get_user_model()


class EmployeeCardOrderTests(TestCase):
    def setUp(self):
        seed_ticket_taxonomy()
        self.company = ResidentCompany.objects.create(
            name="ASBC", slug="asbc-test", portal_active=True, is_internal=False
        )
        self.other = ResidentCompany.objects.create(
            name="Other", slug="other-test", portal_active=True, is_internal=False
        )
        self.user = User.objects.create_user(
            username="office1",
            email="office@asbc-test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        ensure_portal_membership(self.user, self.company)
        self.client = Client()
        self.client.force_login(self.user)
        self.pdf = SimpleUploadedFile("vesiqe.pdf", b"%PDF-1.4 fake", content_type="application/pdf")

    def test_create_employee_card_order_service(self):
        emp, ticket = create_employee_card_order(
            company=self.company,
            requester=self.user,
            full_name="Yeni İşçi",
            id_document=self.pdf,
            access_level="2",
        )
        self.assertEqual(emp.card_number, "")
        self.assertEqual(emp.access_level, "2")
        self.assertEqual(emp.card_order_status, CardOrderStatus.SUBMITTED)
        self.assertTrue(emp.id_document)
        self.assertEqual(ticket.subcategory.slug, "card-order")
        self.assertEqual(ticket.ticket_type, TicketType.SERVICE_REQUEST)
        self.assertEqual(ticket.related_employee_id, emp.pk)
        self.assertEqual(ticket.company_id, self.company.pk)
        self.assertTrue(ticket.attachments.exists())
        self.assertEqual(ticket.department.code, "security")
        self.assertIn("Səviyyə 2", ticket.description)

    def test_create_with_space(self):
        building = Building.objects.create(name="B1", code="B1-CARD")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        space = Space.objects.create(floor=floor, code="S1-CARD", resident=self.company)
        emp, ticket = create_employee_card_order(
            company=self.company,
            requester=self.user,
            full_name="Space Worker",
            id_document=self.pdf,
            access_level="1",
            space=space,
        )
        self.assertEqual(ticket.space_id, space.pk)
        self.assertEqual(emp.full_name, "Space Worker")

    def test_employee_create_redirects_to_request_new(self):
        resp = self.client.get(reverse("portal:employee_create"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/portal/requests/new/", resp["Location"])
        self.assertIn("intent=card_order", resp["Location"])

    def test_prefill_card_order_intent(self):
        building = Building.objects.create(name="B1", code="B1-PRE")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        space = Space.objects.create(floor=floor, code="ONLY-CARD", resident=self.company)
        url = reverse("portal:request_new") + "?intent=card_order"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        form = resp.context["form"]
        self.assertEqual(form.initial.get("ticket_type"), TicketType.SERVICE_REQUEST)
        self.assertEqual(form.fields["ticket_type"].initial, TicketType.SERVICE_REQUEST)
        self.assertTrue(form.initial.get("category"))
        self.assertTrue(form.initial.get("subcategory"))
        self.assertEqual(form.initial.get("space"), space.pk)
        self.assertTrue(resp.context["card_order_intent"])
        prefill = resp.context["card_order_prefill"]
        self.assertEqual(prefill["ticket_type"], TicketType.SERVICE_REQUEST)
        self.assertEqual(prefill["category_slug"], "security")
        self.assertEqual(prefill["subcategory_slug"], "card-order")
        html = resp.content.decode()
        self.assertIn('value="service_request" selected', html)
        self.assertIn(f'value="{prefill["category_id"]}" selected', html)
        self.assertIn(f'value="{prefill["subcategory_id"]}" selected', html)
        self.assertIn("card-order-prefill", html)

    def test_portal_post_creates_order_via_request_new(self):
        from apps.tickets.models import TicketCategory, TicketSubcategory

        cat = TicketCategory.objects.get(slug="security")
        sub = TicketSubcategory.objects.get(slug="card-order", category=cat)
        url = reverse("portal:request_new")
        resp = self.client.post(
            url,
            {
                "intent": "card_order",
                "ticket_type": TicketType.SERVICE_REQUEST,
                "category": cat.pk,
                "subcategory": sub.pk,
                "full_name": "Portal İşçi",
                "access_level": "1",
                "id_document": SimpleUploadedFile(
                    "id.png", b"\x89PNG\r\n", content_type="image/png"
                ),
                "description": "",
            },
        )
        self.assertEqual(resp.status_code, 302)
        emp = ResidentEmployee.objects.get(company=self.company, full_name="Portal İşçi")
        self.assertEqual(emp.card_number, "")
        self.assertEqual(emp.access_level, "1")
        self.assertEqual(emp.card_order_status, CardOrderStatus.SUBMITTED)
        self.assertTrue(
            Ticket.objects.filter(related_employee=emp, subcategory__slug="card-order").exists()
        )

    def test_portal_requires_id_document(self):
        from apps.tickets.models import TicketCategory, TicketSubcategory

        cat = TicketCategory.objects.get(slug="security")
        sub = TicketSubcategory.objects.get(slug="card-order", category=cat)
        resp = self.client.post(
            reverse("portal:request_new"),
            {
                "intent": "card_order",
                "ticket_type": TicketType.SERVICE_REQUEST,
                "category": cat.pk,
                "subcategory": sub.pk,
                "full_name": "No Doc",
                "access_level": "1",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ResidentEmployee.objects.filter(full_name="No Doc").exists())

    def test_portal_requires_access_level(self):
        from apps.tickets.models import TicketCategory, TicketSubcategory

        cat = TicketCategory.objects.get(slug="security")
        sub = TicketSubcategory.objects.get(slug="card-order", category=cat)
        resp = self.client.post(
            reverse("portal:request_new"),
            {
                "intent": "card_order",
                "ticket_type": TicketType.SERVICE_REQUEST,
                "category": cat.pk,
                "subcategory": sub.pk,
                "full_name": "No Level",
                "access_level": "",
                "id_document": SimpleUploadedFile(
                    "id.png", b"\x89PNG\r\n", content_type="image/png"
                ),
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ResidentEmployee.objects.filter(full_name="No Level").exists())

    def test_cannot_add_for_other_company(self):
        emp, ticket = create_employee_card_order(
            company=self.company,
            requester=self.user,
            full_name="Scoped",
            id_document=SimpleUploadedFile("a.pdf", b"%PDF", content_type="application/pdf"),
        )
        self.assertEqual(emp.company_id, self.company.pk)
        self.assertNotEqual(emp.company_id, self.other.pk)

    def test_sync_matches_unlinked_by_name(self):
        emp = ResidentEmployee.objects.create(
            company=self.company, full_name="Match Person", card_number="", is_active=True
        )
        found = _find_unlinked_employee_by_name(self.company, "Match Person")
        self.assertEqual(found.pk, emp.pk)
        ct = ContentType.objects.get_for_model(ResidentEmployee)
        ExternalIdentity.objects.create(
            system="axtraxng",
            external_id="emp:999001",
            entity_type=ct,
            entity_id=emp.pk,
            last_status=SyncStatus.SUCCESS,
        )
        self.assertIsNone(_find_unlinked_employee_by_name(self.company, "Match Person"))


class CardOrderStatusTests(TestCase):
    def setUp(self):
        seed_ticket_taxonomy()
        self.company = ResidentCompany.objects.create(
            name="SecCo", slug="secco", portal_active=True, is_internal=False
        )
        self.portal_user = User.objects.create_user(
            username="portal-sec",
            email="p@secco.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        ensure_portal_membership(self.portal_user, self.company)
        self.security = User.objects.create_user(
            username="sec1",
            email="sec@citypoint.az",
            password="Pass12345!",
            role=Role.SECURITY,
        )
        self.admin = User.objects.create_user(
            username="adm1",
            email="adm@citypoint.az",
            password="Pass12345!",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.pdf = SimpleUploadedFile("id.pdf", b"%PDF-1.4", content_type="application/pdf")
        self.emp, self.ticket = create_employee_card_order(
            company=self.company,
            requester=self.portal_user,
            full_name="Kart Namizəd",
            id_document=self.pdf,
            access_level="1",
        )

    def test_security_can_advance_status(self):
        set_card_order_status(
            employee=self.emp,
            new_status=CardOrderStatus.UNDER_REVIEW,
            actor=self.security,
        )
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.card_order_status, CardOrderStatus.UNDER_REVIEW)

    def test_non_security_cannot_change_status(self):
        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            set_card_order_status(
                employee=self.emp,
                new_status=CardOrderStatus.UNDER_REVIEW,
                actor=self.admin,
            )
        with self.assertRaises(PermissionDenied):
            set_card_order_status(
                employee=self.emp,
                new_status=CardOrderStatus.UNDER_REVIEW,
                actor=self.portal_user,
            )

    def test_security_post_card_order_status(self):
        client = Client()
        client.force_login(self.security)
        url = reverse("security:ticket_detail", kwargs={"code": self.ticket.code})
        resp = client.post(
            url,
            {"action": "card_order_status", "card_order_status": CardOrderStatus.UNDER_REVIEW},
        )
        self.assertEqual(resp.status_code, 302)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.card_order_status, CardOrderStatus.UNDER_REVIEW)

    def test_axtrax_badge_marks_issued_and_closes_ticket(self):
        self.emp.card_number = "778899"
        self.emp.save(update_fields=["card_number"])
        changed = mark_card_order_issued_from_axtrax(self.emp)
        self.assertTrue(changed)
        self.emp.refresh_from_db()
        self.ticket.refresh_from_db()
        self.assertEqual(self.emp.card_order_status, CardOrderStatus.ISSUED)
        self.assertEqual(self.ticket.status, TicketStatus.CLOSED)
