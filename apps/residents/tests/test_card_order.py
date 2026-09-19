from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.integrations.axtrax_people_sync import _find_unlinked_employee_by_name
from apps.integrations.models import ExternalIdentity, SyncStatus
from apps.residents.models import ResidentCompany, ResidentEmployee
from apps.residents.services import create_employee_card_order
from apps.tickets.models import Ticket, TicketSubcategory
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from django.contrib.contenttypes.models import ContentType

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
        self.assertTrue(emp.id_document)
        self.assertEqual(ticket.subcategory.slug, "card-order")
        self.assertEqual(ticket.related_employee_id, emp.pk)
        self.assertEqual(ticket.company_id, self.company.pk)
        self.assertTrue(ticket.attachments.exists())
        self.assertEqual(ticket.department.code, "security")
        self.assertIn("Səviyyə 2", ticket.description)

    def test_portal_post_creates_order(self):
        url = reverse("portal:employee_create")
        resp = self.client.post(
            url,
            {
                "full_name": "Portal İşçi",
                "access_level": "1",
                "id_document": SimpleUploadedFile("id.png", b"\x89PNG\r\n", content_type="image/png"),
            },
        )
        self.assertEqual(resp.status_code, 302)
        emp = ResidentEmployee.objects.get(company=self.company, full_name="Portal İşçi")
        self.assertEqual(emp.card_number, "")
        self.assertEqual(emp.access_level, "1")
        self.assertTrue(
            Ticket.objects.filter(related_employee=emp, subcategory__slug="card-order").exists()
        )

    def test_portal_requires_id_document(self):
        resp = self.client.post(
            reverse("portal:employee_create"),
            {"full_name": "No Doc", "access_level": "1"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ResidentEmployee.objects.filter(full_name="No Doc").exists())

    def test_portal_requires_access_level(self):
        resp = self.client.post(
            reverse("portal:employee_create"),
            {
                "full_name": "No Level",
                "id_document": SimpleUploadedFile("id.png", b"\x89PNG\r\n", content_type="image/png"),
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ResidentEmployee.objects.filter(full_name="No Level").exists())
    def test_cannot_add_for_other_company(self):
        # Logged-in user is bound to self.company; service uses that company only.
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
