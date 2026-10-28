from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.comms.models import Notification
from apps.comms.services import notify_in_app
from apps.core.services import DomainError
from apps.residents.models import ResidentCompany, ResidentEmployee
from apps.tickets.access import (
    can_access_ticket_attachment,
    can_delete_ticket,
    can_mutate_ticket,
    can_view_ticket,
    tickets_visible_to,
)
from apps.tickets.models import (
    Ticket,
    TicketAttachment,
    TicketDepartment,
    TicketPriority,
    TicketStatus,
    TicketCategory,
    TicketSubcategory,
)
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import (
    assign_ticket,
    assign_ticket_employee,
    create_ticket_from_portal,
    delete_ticket,
    handoff_ticket,
    set_ticket_status,
)

User = get_user_model()


class TicketDepartmentAccessTests(TestCase):
    def test_fire_is_security_and_repair_is_under_technical(self):
        seed_ticket_taxonomy()
        fire = TicketSubcategory.objects.get(slug="fire", is_active=True)
        self.assertEqual(fire.category.slug, "security")
        self.assertEqual(fire.name, "Yanğın sistemi")
        self.assertEqual(fire.routing_rule.department.code, "security")
        card_related = TicketSubcategory.objects.get(slug="card-related", category__slug="security")
        self.assertEqual(card_related.name, "Kartla bağlı")
        self.assertEqual(card_related.routing_rule.department.code, "security")
        self.assertLess(card_related.sort_order, 1000)
        cargo = TicketSubcategory.objects.get(slug="cargo", category__slug="security")
        event = TicketSubcategory.objects.get(slug="event", category__slug="security")
        self.assertEqual(cargo.name, "Yük daşıma")
        self.assertEqual(event.name, "Tədbir")
        self.assertEqual(cargo.routing_rule.department.code, "security")
        self.assertEqual(event.routing_rule.department.code, "security")
        repair = TicketSubcategory.objects.get(slug="repair", category__slug="technical")
        partition = TicketSubcategory.objects.get(slug="new-partition", category__slug="technical")
        self.assertEqual(repair.name, "Təmir")
        self.assertEqual(partition.name, "Yeni Bölgü")
        self.assertEqual(repair.routing_rule.department.code, "servicedesk")
        self.assertEqual(partition.routing_rule.department.code, "servicedesk")
        self.assertFalse(
            TicketSubcategory.objects.filter(slug="repair-new-partition", is_active=True).exists()
        )
        self.assertFalse(
            TicketSubcategory.objects.filter(category__slug="technical", slug="fire", is_active=True).exists()
        )
        self.assertFalse(
            TicketSubcategory.objects.filter(
                category__slug="security", slug="access-fault", is_active=True
            ).exists()
        )
        self.assertFalse(
            TicketSubcategory.objects.filter(
                category__slug="commercial-space",
                slug__in=("additional-office", "different-floor"),
                is_active=True,
            ).exists()
        )
        matter = TicketSubcategory.objects.get(slug="lease-matter", category__slug="lease")
        agreement = TicketSubcategory.objects.get(slug="additional-agreement", category__slug="lease")
        self.assertEqual(matter.name, "Müqavilə ilə bağlı")
        self.assertEqual(agreement.name, "Əlavə razılaşma")
        self.assertFalse(
            TicketSubcategory.objects.filter(category__slug="lease", slug="lease-question", is_active=True).exists()
        )
        self.assertEqual(matter.routing_rule.department.code, "property")
        self.assertEqual(agreement.routing_rule.department.code, "property")
        rent = TicketSubcategory.objects.get(slug="rent-payment", category__slug="billing")
        extras = TicketSubcategory.objects.get(slug="extra-services-payment", category__slug="billing")
        deposit = TicketSubcategory.objects.get(slug="deposit", category__slug="billing")
        self.assertEqual(rent.name, "İcarə ödənişi")
        self.assertEqual(extras.name, "Əlavə xidmətlər ödənişi")
        self.assertEqual(deposit.name, "Depozit")
        self.assertEqual(rent.routing_rule.department.code, "accounting")
        for category in TicketCategory.objects.filter(is_active=True):
            last = category.subcategories.filter(is_active=True).order_by("sort_order", "name").last()
            self.assertIsNotNone(last, category.slug)
            self.assertEqual(last.name, "Digər", category.slug)

    def setUp(self):
        seed_ticket_taxonomy()
        self.company_a = ResidentCompany.objects.create(
            name="Co A", slug="co-a", portal_active=True, is_internal=False
        )
        self.company_b = ResidentCompany.objects.create(
            name="Co B", slug="co-b", portal_active=True, is_internal=False
        )
        self.sec_dept = TicketDepartment.objects.get(code="security")
        self.fm_dept = TicketDepartment.objects.get(code="webservis")
        self.desk_dept = TicketDepartment.objects.get(code="servicedesk")
        self.admin = User.objects.create_user(
            username="admin1",
            email="admin@test.az",
            password="Pass12345!",
            role=Role.ADMIN,
        )
        self.sec_user = User.objects.create_user(
            username="sec1",
            email="sec@test.az",
            password="Pass12345!",
            role=Role.SECURITY,
            ticket_department=self.sec_dept,
        )
        self.fm_user = User.objects.create_user(
            username="fm1",
            email="fm@test.az",
            password="Pass12345!",
            role=Role.PROPERTY_FM,
            ticket_department=self.fm_dept,
        )
        self.desk_user = User.objects.create_user(
            username="desk1",
            email="desk@test.az",
            password="Pass12345!",
            role=Role.SERVICE_DESK,
            ticket_department=self.desk_dept,
        )
        self.no_dept = User.objects.create_user(
            username="nodesk",
            email="nodesk@test.az",
            password="Pass12345!",
            role=Role.SERVICE_DESK,
        )
        self.resident_a = User.objects.create_user(
            username="resa",
            email="resa@coa.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company_a,
        )
        self.resident_b = User.objects.create_user(
            username="resb",
            email="resb@cob.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company_b,
        )
        self.sec_sub = TicketSubcategory.objects.get(slug="security-incident")
        self.fm_sub = TicketSubcategory.objects.get(slug="electric")
        self.sec_ticket = create_ticket_from_portal(
            company=self.company_a,
            requester=self.resident_a,
            ticket_type="incident",
            category=self.sec_sub.category,
            subcategory=self.sec_sub,
            description="Security issue near lobby",
        )
        self.fm_ticket = create_ticket_from_portal(
            company=self.company_b,
            requester=self.resident_b,
            ticket_type="incident",
            category=self.fm_sub.category,
            subcategory=self.fm_sub,
            description="Electric fault in office",
        )
        self.client = Client()

    def test_visibility_by_department(self):
        self.assertTrue(can_view_ticket(self.admin, self.sec_ticket))
        self.assertTrue(can_view_ticket(self.admin, self.fm_ticket))
        self.assertTrue(can_view_ticket(self.sec_user, self.sec_ticket))
        self.assertFalse(can_view_ticket(self.sec_user, self.fm_ticket))
        self.assertEqual(self.fm_ticket.department_id, self.desk_dept.pk)
        self.assertTrue(can_view_ticket(self.desk_user, self.fm_ticket))
        self.assertFalse(can_view_ticket(self.fm_user, self.fm_ticket))
        self.assertFalse(can_view_ticket(self.fm_user, self.sec_ticket))
        self.assertEqual(tickets_visible_to(self.no_dept).count(), 0)
        self.assertFalse(can_view_ticket(self.no_dept, self.sec_ticket))

    def test_technical_and_cleaning_route_to_service_desk(self):
        cleaning = TicketSubcategory.objects.get(slug="office-cleaning")
        ticket = create_ticket_from_portal(
            company=self.company_a,
            requester=self.resident_a,
            ticket_type="incident",
            category=cleaning.category,
            subcategory=cleaning,
            description="Lobby needs cleaning",
        )
        self.assertEqual(ticket.department.code, "servicedesk")
        self.assertEqual(ticket.queue.code, "cleaning")
        self.assertTrue(can_view_ticket(self.desk_user, ticket))
        self.assertFalse(can_view_ticket(self.fm_user, ticket))
        self.assertTrue(
            tickets_visible_to(self.desk_user).filter(pk__in=[ticket.pk, self.fm_ticket.pk]).count(),
            2,
        )

    def test_portal_routes_to_target_department(self):
        parking = TicketSubcategory.objects.get(slug="parking-extra")
        ticket = create_ticket_from_portal(
            company=self.company_a,
            requester=self.resident_a,
            ticket_type="incident",
            category=parking.category,
            subcategory=parking,
            description="Extra parking from the resident portal",
        )
        self.assertEqual(ticket.department.code, "commercial")
        self.assertEqual(ticket.queue.code, "parking")
        self.assertFalse(can_view_ticket(self.desk_user, ticket))
        self.assertFalse(can_view_ticket(self.sec_user, ticket))

        electric = create_ticket_from_portal(
            company=self.company_a,
            requester=self.resident_a,
            ticket_type="incident",
            category=self.fm_sub.category,
            subcategory=self.fm_sub,
            description="Electric fault reported from the portal",
        )
        self.assertEqual(electric.department.code, "servicedesk")
        self.assertEqual(electric.queue.code, "electric")
        self.assertTrue(can_view_ticket(self.desk_user, electric))

        self.client.force_login(self.resident_a)
        resp = self.client.post(
            reverse("portal:request_new"),
            {
                "ticket_type": "incident",
                "category": self.sec_sub.category_id,
                "subcategory": self.sec_sub.pk,
                "description": "Lobby incident from ASBC portal",
            },
        )
        self.assertEqual(resp.status_code, 302)
        created = Ticket.objects.get(description="Lobby incident from ASBC portal")
        self.assertEqual(created.department.code, "security")
        self.assertEqual(created.queue.code, "security")
        self.assertTrue(can_view_ticket(self.sec_user, created))
        self.assertFalse(can_view_ticket(self.desk_user, created))

    def test_delete_allowed_before_in_progress(self):
        self.assertTrue(can_delete_ticket(self.sec_user, self.sec_ticket))
        self.assertTrue(can_delete_ticket(self.resident_a, self.sec_ticket))
        self.assertFalse(can_delete_ticket(self.fm_user, self.sec_ticket))
        self.assertFalse(can_delete_ticket(self.resident_b, self.sec_ticket))

        set_ticket_status(self.sec_ticket, TicketStatus.ACCEPTED, actor=self.sec_user)
        self.sec_ticket.refresh_from_db()
        self.assertTrue(can_delete_ticket(self.sec_user, self.sec_ticket))

        set_ticket_status(self.sec_ticket, TicketStatus.IN_PROGRESS, actor=self.sec_user)
        self.sec_ticket.refresh_from_db()
        self.assertFalse(can_delete_ticket(self.sec_user, self.sec_ticket))
        with self.assertRaises(DomainError):
            delete_ticket(self.sec_ticket, actor=self.sec_user)

        doomed = create_ticket_from_portal(
            company=self.company_a,
            requester=self.resident_a,
            ticket_type="incident",
            category=self.sec_sub.category,
            subcategory=self.sec_sub,
            description="Will be deleted before in progress",
        )
        code = doomed.code
        self.client.force_login(self.sec_user)
        resp = self.client.post(
            reverse("security:ticket_detail", kwargs={"code": code}),
            {"action": "delete"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Ticket.objects.filter(code=code).exists())

        portal_doomed = create_ticket_from_portal(
            company=self.company_a,
            requester=self.resident_a,
            ticket_type="incident",
            category=self.sec_sub.category,
            subcategory=self.sec_sub,
            description="Portal self-delete before in progress",
        )
        portal_code = portal_doomed.code
        self.client.force_login(self.resident_a)
        resp = self.client.post(
            reverse("portal:request_detail", kwargs={"code": portal_code}),
            {"action": "delete"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Ticket.objects.filter(code=portal_code).exists())

    def test_erp_list_and_detail_scoped(self):
        self.client.force_login(self.desk_user)
        resp = self.client.get(reverse("erp:tickets"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.fm_ticket.code)
        self.assertNotContains(resp, self.sec_ticket.code)

        ok = self.client.get(reverse("erp:ticket_detail", kwargs={"code": self.fm_ticket.code}))
        self.assertEqual(ok.status_code, 200)
        forbidden = self.client.get(
            reverse("erp:ticket_detail", kwargs={"code": self.sec_ticket.code})
        )
        self.assertEqual(forbidden.status_code, 404)

    def test_security_list_uses_fk_not_hardcode(self):
        self.client.force_login(self.sec_user)
        resp = self.client.get(reverse("security:tickets"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.sec_ticket.code)
        self.assertNotContains(resp, self.fm_ticket.code)

    def test_attachment_staff_and_resident(self):
        upload = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
        att = TicketAttachment.objects.create(ticket=self.sec_ticket, file=upload)
        url = reverse("ticket_attachment_download", kwargs={"pk": att.pk})

        self.assertTrue(can_access_ticket_attachment(self.sec_user, self.sec_ticket))
        self.assertFalse(can_access_ticket_attachment(self.fm_user, self.sec_ticket))
        self.assertTrue(can_access_ticket_attachment(self.resident_a, self.sec_ticket))
        self.assertFalse(can_access_ticket_attachment(self.resident_b, self.sec_ticket))

        self.client.force_login(self.sec_user)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.fm_user)
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.resident_a)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.resident_b)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_service_layer_rejects_cross_dept_status(self):
        self.assertFalse(can_mutate_ticket(self.fm_user, self.sec_ticket))
        with self.assertRaises(DomainError):
            set_ticket_status(
                self.sec_ticket, TicketStatus.ACCEPTED, actor=self.fm_user
            )
        self.sec_ticket.refresh_from_db()
        self.assertEqual(self.sec_ticket.status, TicketStatus.SENT)

    def test_status_waiting_requires_reason(self):
        set_ticket_status(self.sec_ticket, TicketStatus.ACCEPTED, actor=self.sec_user)
        set_ticket_status(self.sec_ticket, TicketStatus.IN_PROGRESS, actor=self.sec_user)
        with self.assertRaises(DomainError):
            set_ticket_status(self.sec_ticket, TicketStatus.WAITING, actor=self.sec_user)
        set_ticket_status(
            self.sec_ticket,
            TicketStatus.WAITING,
            actor=self.sec_user,
            waiting_reason="Spare part",
        )
        self.sec_ticket.refresh_from_db()
        self.assertEqual(self.sec_ticket.status, TicketStatus.WAITING)

    def test_service_desk_assigns_citypoint_employee_by_name(self):
        city = ResidentCompany.objects.create(
            name="City Point", slug="city-point", is_internal=True
        )
        worker = ResidentEmployee.objects.create(company=city, full_name="Anar Texnik")
        outsider = ResidentEmployee.objects.create(
            company=self.company_a, full_name="Basqa Adam"
        )
        assign_ticket_employee(self.fm_ticket, actor=self.desk_user, employee_id=worker.pk)
        self.fm_ticket.refresh_from_db()
        self.assertEqual(self.fm_ticket.assigned_employee_id, worker.pk)
        self.assertEqual(self.fm_ticket.status, TicketStatus.ASSIGNED)
        with self.assertRaises(DomainError):
            assign_ticket_employee(
                self.fm_ticket, actor=self.desk_user, employee_id=outsider.pk
            )

        self.client.force_login(self.desk_user)
        page = self.client.get(reverse("erp:ticket_detail", kwargs={"code": self.fm_ticket.code}))
        self.assertContains(page, 'id="assignee-search"')
        self.assertContains(page, "Anar Texnik")
        self.assertNotContains(page, "Basqa Adam")
        saved = self.client.post(
            reverse("erp:ticket_detail", kwargs={"code": self.fm_ticket.code}),
            {"action": "assign", "assignee": str(worker.pk)},
        )
        self.assertEqual(saved.status_code, 302)
        self.fm_ticket.refresh_from_db()
        self.assertEqual(self.fm_ticket.assigned_employee_id, worker.pk)

    def test_service_desk_creates_detailed_ticket(self):
        city = ResidentCompany.objects.create(
            name="City Point", slug="city-point", is_internal=True
        )
        worker = ResidentEmployee.objects.create(company=city, full_name="Kamran Usta")
        sub = TicketSubcategory.objects.get(slug="electric")
        self.client.force_login(self.desk_user)
        form_page = self.client.get(reverse("erp:ticket_create"))
        self.assertEqual(form_page.status_code, 200)
        self.assertContains(form_page, "id_category")
        self.assertContains(form_page, "id_company")
        response = self.client.post(
            reverse("erp:ticket_create"),
            {
                "company": self.company_a.pk,
                "ticket_type": "incident",
                "category": sub.category_id,
                "subcategory": sub.pk,
                "priority": TicketPriority.HIGH,
                "assigned_employee": worker.pk,
                "description": "Koridorda işıq yanmır.",
            },
        )
        ticket = Ticket.objects.get(description="Koridorda işıq yanmır.")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("erp:ticket_detail", kwargs={"code": ticket.code}))
        self.assertEqual(ticket.company_id, self.company_a.pk)
        self.assertEqual(ticket.subcategory_id, sub.pk)
        self.assertEqual(ticket.assigned_employee_id, worker.pk)
        self.assertEqual(ticket.priority, TicketPriority.HIGH)
        self.assertEqual(ticket.department.code, "servicedesk")
        self.assertEqual(ticket.status, TicketStatus.ASSIGNED)

    def test_assignee_must_be_same_dept(self):
        with self.assertRaises(DomainError):
            assign_ticket(
                self.sec_ticket, actor=self.sec_user, assignee_id=self.fm_user.pk
            )
        assign_ticket(self.sec_ticket, actor=self.sec_user, assignee_id=self.sec_user.pk)
        self.sec_ticket.refresh_from_db()
        self.assertEqual(self.sec_ticket.assignee_id, self.sec_user.pk)

    def test_holding_department_can_handoff(self):
        with self.assertRaises(DomainError):
            handoff_ticket(
                self.sec_ticket,
                actor=self.desk_user,
                department_id=self.desk_dept.pk,
            )
        with self.assertRaises(DomainError):
            handoff_ticket(
                self.sec_ticket,
                actor=self.resident_a,
                department_id=self.desk_dept.pk,
            )
        handoff_ticket(
            self.sec_ticket,
            actor=self.sec_user,
            department_id=self.desk_dept.pk,
            note="wrong category",
        )
        self.sec_ticket.refresh_from_db()
        self.assertEqual(self.sec_ticket.department_id, self.desk_dept.pk)
        self.assertIsNone(self.sec_ticket.assignee_id)
        self.assertIsNone(self.sec_ticket.assigned_employee_id)
        self.assertTrue(self.sec_ticket.routing_events.filter(note="wrong category").exists())
        with self.assertRaises(DomainError):
            handoff_ticket(
                self.sec_ticket,
                actor=self.desk_user,
                department_id=self.desk_dept.pk,
            )

    def test_resident_cannot_mutate_status(self):
        self.assertFalse(can_mutate_ticket(self.resident_a, self.sec_ticket))
        with self.assertRaises(DomainError):
            set_ticket_status(
                self.sec_ticket, TicketStatus.ACCEPTED, actor=self.resident_a
            )

    def test_portal_company_scope(self):
        self.client.force_login(self.resident_a)
        ok = self.client.get(
            reverse("portal:request_detail", kwargs={"code": self.sec_ticket.code})
        )
        self.assertEqual(ok.status_code, 200)
        other = self.client.get(
            reverse("portal:request_detail", kwargs={"code": self.fm_ticket.code})
        )
        self.assertEqual(other.status_code, 404)

    def test_notify_event_key_dedup(self):
        key = "ticket.status.test.1"
        n1 = notify_in_app(user=self.sec_user, message="Same text", event_key=key)
        n2 = notify_in_app(user=self.sec_user, message="Same text", event_key=key)
        self.assertEqual(n1.pk, n2.pk)
        self.assertEqual(
            Notification.objects.filter(user=self.sec_user, event_key=key).count(), 1
        )
        n3 = notify_in_app(
            user=self.sec_user, message="Same text", event_key="ticket.status.test.2"
        )
        self.assertNotEqual(n1.pk, n3.pk)
        self.assertEqual(
            Notification.objects.filter(user=self.sec_user, message="Same text").count(),
            2,
        )


class TicketNotifyOnCommitTests(TransactionTestCase):
    def setUp(self):
        seed_ticket_taxonomy()
        self.company = ResidentCompany.objects.create(
            name="Notify Co", slug="notify-co", portal_active=True, is_internal=False
        )
        self.sec_dept = TicketDepartment.objects.get(code="security")
        self.sec_user = User.objects.create_user(
            username="secn",
            email="secn@test.az",
            password="Pass12345!",
            role=Role.SECURITY,
            ticket_department=self.sec_dept,
        )
        self.resident = User.objects.create_user(
            username="resn",
            email="resn@notify.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        self.sub = TicketSubcategory.objects.get(slug="security-incident")

    def test_status_notify_fires_after_commit(self):
        ticket = create_ticket_from_portal(
            company=self.company,
            requester=self.resident,
            ticket_type="incident",
            category=self.sub.category,
            subcategory=self.sub,
            description="Notify path check for security",
        )
        before = Notification.objects.filter(user=self.resident).count()
        set_ticket_status(ticket, TicketStatus.ACCEPTED, actor=self.sec_user)
        after = Notification.objects.filter(user=self.resident).count()
        self.assertGreater(after, before)
        self.assertTrue(
            Notification.objects.filter(
                user=self.resident, event_key__startswith=f"ticket.status.{ticket.pk}."
            ).exists()
        )
