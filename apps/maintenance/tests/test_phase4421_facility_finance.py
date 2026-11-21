"""Phase 4.4.2.1 — Accountant lease-app discoverability, standalone WO, WO ACL, reception nav."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.nav import build_nav_flags
from apps.crm.models import LeaseApplication, LeaseApplicationStatus
from apps.maintenance.access import (
    can_create_standalone_work_order,
    can_mutate_work_order,
    can_view_work_order,
    work_orders_queryset_for,
)
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from apps.maintenance.services import create_standalone_work_order
from apps.rbac.services import seed_rbac_catalog, user_has_permission
from apps.residents.models import ResidentCompany
from apps.tickets.models import (
    Ticket,
    TicketCategory,
    TicketDepartment,
    TicketPriority,
    TicketStatus,
    TicketSubcategory,
    TicketType,
)
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import create_work_order_from_ticket

User = get_user_model()


class Phase4421AccountantLeaseAppNavTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def setUp(self):
        self.client = Client()
        self.acct = User.objects.create_user(
            username="p4421-acct",
            email="p4421-acct@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.sales = User.objects.create_user(
            username="p4421-sales",
            email="p4421-sales@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )

    def test_accountant_sees_lease_app_nav_on_finance_home(self):
        self.client.force_login(self.acct)
        resp = self.client.get(reverse("finance:home"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Müqavilə müraciətləri", body)
        self.assertIn(reverse("erp:crm_lease_applications"), body)
        self.assertIn("queue=1", body)

    def test_accountant_opens_queue_and_detail(self):
        app = LeaseApplication.objects.create(
            person_name="P4421 Applicant",
            status=LeaseApplicationStatus.SUBMITTED_TO_ACCOUNTING,
        )
        self.client.force_login(self.acct)
        queue = self.client.get(reverse("erp:crm_lease_applications") + "?queue=1")
        self.assertEqual(queue.status_code, 200)
        self.assertContains(queue, "P4421 Applicant")
        detail = self.client.get(reverse("erp:crm_lease_application_detail", kwargs={"pk": app.pk}))
        self.assertEqual(detail.status_code, 200)

    def test_sales_finance_home_denied(self):
        self.client.force_login(self.sales)
        resp = self.client.get(reverse("finance:home"))
        self.assertEqual(resp.status_code, 302)


class Phase4421StandaloneWorkOrderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        seed_ticket_taxonomy()
        cls.company = ResidentCompany.objects.create(name="P4421 WO Co", slug="p4421-wo")
        cls.desk_dept = TicketDepartment.objects.get(code="servicedesk")
        cls.fm_dept = TicketDepartment.objects.get(code="webservis")
        cls.hvac = TicketSubcategory.objects.filter(slug="hvac").first()
        cls.cat = cls.hvac.category if cls.hvac else TicketCategory.objects.filter(is_active=True).first()

    def setUp(self):
        self.client = Client()
        self.fm = User.objects.create_user(
            username="p4421-fm",
            email="p4421-fm@test.az",
            password="x",
            role=Role.PROPERTY_FM,
            is_staff=True,
            ticket_department=self.fm_dept,
        )
        self.desk = User.objects.create_user(
            username="p4421-desk",
            email="p4421-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
            ticket_department=self.desk_dept,
        )
        self.mgmt = User.objects.create_user(
            username="p4421-mgmt",
            email="p4421-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.reception = User.objects.create_user(
            username="p4421-rec",
            email="p4421-rec@test.az",
            password="x",
            role=Role.RECEPTION,
            is_staff=True,
        )

    def test_fm_create_form_and_standalone_wo(self):
        self.assertTrue(can_create_standalone_work_order(self.fm))
        self.assertFalse(can_create_standalone_work_order(self.desk))
        self.assertFalse(can_create_standalone_work_order(self.mgmt))

        self.client.force_login(self.fm)
        form = self.client.get(reverse("erp:work_order_create"))
        self.assertEqual(form.status_code, 200)
        self.assertContains(form, "Yeni iş tapşırığı")

        token = form.context["submit_token"]
        create = self.client.post(
            reverse("erp:work_order_create"),
            {
                "title": "HVAC panel yoxlama",
                "description": "Daxili texniki baxış",
                "priority": WorkOrderPriority.HIGH,
                "submit_token": token,
            },
        )
        self.assertEqual(create.status_code, 302)
        wo = WorkOrder.objects.get(title="HVAC panel yoxlama")
        self.assertIsNone(wo.ticket_id)
        self.assertEqual(wo.status, WorkOrderStatus.OPEN)
        self.assertEqual(create.url, reverse("erp:work_order_detail", kwargs={"code": wo.code}))

        # Duplicate submit with same token does not create another WO.
        before = WorkOrder.objects.count()
        dup = self.client.post(
            reverse("erp:work_order_create"),
            {
                "title": "HVAC panel yoxlama",
                "description": "Daxili texniki baxış",
                "priority": WorkOrderPriority.HIGH,
                "submit_token": token,
            },
        )
        self.assertEqual(dup.status_code, 302)
        self.assertEqual(WorkOrder.objects.count(), before)

        list_resp = self.client.get(reverse("erp:work_orders"))
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, wo.code)
        self.assertContains(list_resp, "Facility")

        detail = self.client.get(reverse("erp:work_order_detail", kwargs={"code": wo.code}))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Facility")

        status = self.client.post(
            reverse("erp:work_order_detail", kwargs={"code": wo.code}),
            {"action": "status", "status": WorkOrderStatus.IN_PROGRESS},
        )
        self.assertEqual(status.status_code, 302)
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrderStatus.IN_PROGRESS)

        self.client.post(
            reverse("erp:work_order_detail", kwargs={"code": wo.code}),
            {"action": "status", "status": WorkOrderStatus.COMPLETED},
        )
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrderStatus.COMPLETED)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_desk_cannot_create_or_see_standalone(self):
        wo = create_standalone_work_order(
            title="Orphan FM WO",
            actor=self.fm,
        )
        self.assertFalse(can_view_work_order(self.desk, wo))
        self.assertFalse(work_orders_queryset_for(self.desk).filter(pk=wo.pk).exists())

        self.client.force_login(self.desk)
        form = self.client.get(reverse("erp:work_order_create"))
        self.assertIn(form.status_code, (302, 403))
        detail = self.client.get(reverse("erp:work_order_detail", kwargs={"code": wo.code}))
        self.assertIn(detail.status_code, (302, 403, 404))

    def test_mgmt_view_no_mutate_standalone(self):
        wo = create_standalone_work_order(title="Mgmt RO WO", actor=self.fm)
        self.assertTrue(can_view_work_order(self.mgmt, wo))
        self.assertFalse(can_mutate_work_order(self.mgmt, wo))
        self.client.force_login(self.mgmt)
        detail = self.client.get(reverse("erp:work_order_detail", kwargs={"code": wo.code}))
        self.assertEqual(detail.status_code, 200)
        denied = self.client.post(
            reverse("erp:work_order_detail", kwargs={"code": wo.code}),
            {"action": "status", "status": WorkOrderStatus.CANCELLED},
        )
        self.assertIn(denied.status_code, (302, 403))
        wo.refresh_from_db()
        self.assertNotEqual(wo.status, WorkOrderStatus.CANCELLED)

    def test_ticket_linked_create_still_works(self):
        ticket = Ticket.objects.create(
            code="TK-P4421-1",
            ticket_type=TicketType.INCIDENT,
            category=self.cat,
            subcategory=self.hvac,
            company=self.company,
            description="linked",
            priority=TicketPriority.NORMAL,
            status=TicketStatus.IN_PROGRESS,
            department=self.desk_dept,
            sla_due_at=timezone.now() + timedelta(hours=8),
        )
        wo = create_work_order_from_ticket(ticket, actor=self.desk)
        self.assertEqual(wo.ticket_id, ticket.pk)
        self.assertTrue(can_view_work_order(self.desk, wo))
        self.assertTrue(can_view_work_order(self.fm, wo))

    def test_wo_acl_without_ticket_view_gate(self):
        """FM WO access uses work_order.view, not ticket.view as hard gate."""
        self.assertTrue(user_has_permission(self.fm, "work_order.view"))
        self.assertTrue(user_has_permission(self.fm, "work_order.create"))
        self.assertTrue(user_has_permission(self.desk, "work_order.view"))
        self.assertFalse(user_has_permission(self.desk, "work_order.create"))
        self.assertTrue(user_has_permission(self.mgmt, "work_order.view"))
        self.assertFalse(user_has_permission(self.mgmt, "work_order.edit"))
        self.assertFalse(user_has_permission(self.reception, "work_order.view"))

        wo = create_standalone_work_order(title="ACL check", actor=self.fm)
        self.client.force_login(self.reception)
        resp = self.client.get(reverse("erp:work_order_detail", kwargs={"code": wo.code}))
        self.assertIn(resp.status_code, (302, 403, 404))

    def test_ticket_link_redacted_for_cross_dept(self):
        ticket = Ticket.objects.create(
            code="TK-P4421-HD",
            ticket_type=TicketType.INCIDENT,
            category=self.cat,
            subcategory=self.hvac,
            company=self.company,
            description="confidential helpdesk text",
            priority=TicketPriority.NORMAL,
            status=TicketStatus.IN_PROGRESS,
            department=self.desk_dept,
            sla_due_at=timezone.now() + timedelta(hours=8),
        )
        wo = create_work_order_from_ticket(ticket, actor=self.desk)
        self.client.force_login(self.fm)
        detail = self.client.get(reverse("erp:work_order_detail", kwargs={"code": wo.code}))
        self.assertEqual(detail.status_code, 200)
        # FM sees WO; ticket deep-link redacted when ticket.view scope fails.
        self.assertFalse(detail.context["can_view_ticket_link"])
        self.assertContains(detail, "məhdud")
        self.assertNotContains(
            detail,
            reverse("erp:ticket_detail", kwargs={"code": ticket.code}),
        )


class Phase4421ReceptionNavTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def test_fm_nav_hides_reception_desk(self):
        fm = User.objects.create_user(
            username="p4421-fm-nav",
            email="p4421-fm-nav@test.az",
            password="x",
            role=Role.PROPERTY_FM,
            is_staff=True,
        )
        # Intentional RO API grant remains; desk nav must stay hidden.
        self.assertTrue(user_has_permission(fm, "reception.view"))
        flags = build_nav_flags(fm)
        self.assertFalse(flags["nav_reception"])

    def test_reception_and_admin_keep_nav(self):
        rec = User.objects.create_user(
            username="p4421-rec-nav",
            email="p4421-rec-nav@test.az",
            password="x",
            role=Role.RECEPTION,
            is_staff=True,
        )
        admin = User.objects.create_user(
            username="p4421-adm-nav",
            email="p4421-adm-nav@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.assertTrue(build_nav_flags(rec)["nav_reception"])
        self.assertTrue(build_nav_flags(admin)["nav_reception"])

    def test_mgmt_nav_hides_reception_desk(self):
        mgmt = User.objects.create_user(
            username="p4421-mgmt-nav",
            email="p4421-mgmt-nav@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.assertFalse(build_nav_flags(mgmt)["nav_reception"])
