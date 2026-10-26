from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.comms.models import Notification
from apps.residents.models import ResidentCompany
from apps.tickets.models import TicketDepartment, TicketSubcategory
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import create_ticket_from_portal

User = get_user_model()


class NotificationLinkTests(TestCase):
    def setUp(self):
        seed_ticket_taxonomy()
        self.company = ResidentCompany.objects.create(
            name="ASBC", slug="asbc-notes", portal_active=True, is_internal=False
        )
        self.other = ResidentCompany.objects.create(
            name="Other", slug="other-notes", portal_active=True, is_internal=False
        )
        self.resident = User.objects.create_user(
            username="note-res",
            email="note-res@asbc.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        self.desk = User.objects.create_user(
            username="note-desk",
            email="note-desk@test.az",
            password="Pass12345!",
            role=Role.SERVICE_DESK,
            ticket_department=TicketDepartment.objects.get(code="servicedesk"),
        )
        self.security = User.objects.create_user(
            username="note-sec",
            email="note-sec@test.az",
            password="Pass12345!",
            role=Role.SECURITY,
            ticket_department=TicketDepartment.objects.get(code="security"),
        )
        electric = TicketSubcategory.objects.get(slug="electric")
        incident = TicketSubcategory.objects.get(slug="security-incident")
        self.desk_ticket = create_ticket_from_portal(
            company=self.company,
            requester=self.resident,
            ticket_type="incident",
            category=electric.category,
            subcategory=electric,
            description="Lamp is out",
        )
        self.sec_ticket = create_ticket_from_portal(
            company=self.company,
            requester=self.resident,
            ticket_type="incident",
            category=incident.category,
            subcategory=incident,
            description="Lobby incident",
        )
        self.foreign = create_ticket_from_portal(
            company=self.other,
            requester=self.resident,
            ticket_type="incident",
            category=electric.category,
            subcategory=electric,
            description="Other company lamp",
        )
        Notification.objects.create(
            user=self.resident,
            ticket=self.desk_ticket,
            message=f"{self.desk_ticket.code} statusu: Yenidən açıldı",
        )
        Notification.objects.create(
            user=self.resident,
            message=f"{self.foreign.code} statusu: Bağlandı",
        )
        Notification.objects.create(
            user=self.resident,
            message="Ümumi elan mətni",
        )
        Notification.objects.create(
            user=self.desk,
            message=f"{self.desk_ticket.code} şöbəyə yönləndirildi",
        )
        Notification.objects.create(
            user=self.desk,
            ticket=self.sec_ticket,
            message=f"{self.sec_ticket.code} statusu: Göndərildi",
        )
        Notification.objects.create(
            user=self.security,
            ticket=self.sec_ticket,
            message=f"{self.sec_ticket.code} statusu: Göndərildi",
        )
        Notification.objects.create(
            user=self.security,
            message="Şaxta açıldı: Test (ASBC) · F1Shaft",
        )
        self.client = Client()

    def test_portal_notification_opens_own_ticket(self):
        self.client.force_login(self.resident)
        resp = self.client.get(reverse("portal:alerts"))
        own = reverse("portal:request_detail", kwargs={"code": self.desk_ticket.code})
        foreign = reverse("portal:request_detail", kwargs={"code": self.foreign.code})
        self.assertContains(resp, f'class="cp-list-row" href="{own}"')
        self.assertNotContains(resp, f'href="{foreign}"')
        self.assertContains(resp, "Ümumi elan mətni")
        note = Notification.objects.get(user=self.resident, ticket=self.desk_ticket)
        self.assertTrue(note.is_read)

    def test_erp_notification_opens_visible_ticket_only(self):
        self.client.force_login(self.desk)
        resp = self.client.get(reverse("erp:alerts"))
        own = reverse("erp:ticket_detail", kwargs={"code": self.desk_ticket.code})
        hidden = reverse("erp:ticket_detail", kwargs={"code": self.sec_ticket.code})
        self.assertContains(resp, f'class="cp-list-row" href="{own}"')
        self.assertNotContains(resp, f'href="{hidden}"')
        self.assertContains(resp, self.sec_ticket.code)

    def test_security_notification_opens_ticket_and_shaft_list(self):
        self.client.force_login(self.security)
        resp = self.client.get(reverse("security:alerts"))
        ticket_url = reverse("security:ticket_detail", kwargs={"code": self.sec_ticket.code})
        shaft_url = reverse("security:alerts_shaft")
        self.assertContains(resp, f'class="cp-list-row" href="{ticket_url}"')
        self.assertContains(resp, f'class="cp-list-row" href="{shaft_url}"')
