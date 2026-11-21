from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.rbac.services import seed_rbac_catalog
from apps.audit.models import AuditLog
from apps.audit.present import visible_logs
from apps.audit.services import log_action
from apps.core.events import VISITOR_CHECKED_IN
from apps.reception.services import ReceptionService
from apps.residents.models import ResidentCompany

User = get_user_model()


class AdminAuditLogTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.company = ResidentCompany.objects.create(name="Ryumka MMC", slug="ryumka-audit")
        self.admin = User.objects.create_user(
            username="audit-admin",
            email="admin@citypoint.az",
            password="admin123",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
            first_name="Admin",
        )
        self.aygun = User.objects.create_user(
            username="aygun",
            email="aygun@citypoint.az",
            password="pass12345",
            role=Role.RECEPTION,
            is_staff=True,
            first_name="Aygün",
            last_name="Məmmədova",
        )
        self.elcin = User.objects.create_user(
            username="elcin",
            email="elcin@citypoint.az",
            password="pass12345",
            role=Role.RECEPTION,
            is_staff=True,
            first_name="Elçin",
            last_name="Quliyev",
        )
        self.desk = User.objects.create_user(
            username="desk",
            email="desk@citypoint.az",
            password="desk123",
            role=Role.SERVICE_DESK,
            is_staff=True,
            first_name="Service",
            last_name="Desk",
        )
        from apps.reception.models import VisitorType

        courier, _ = VisitorType.objects.get_or_create(
            code="courier", defaults={"name": "Kuryer", "sort_order": 10}
        )
        self.nigar = ReceptionService.register_walk_in(
            fin_code="",
            first_name="Nigar",
            last_name="Əliyeva",
            company=self.company,
            visit_type=courier,
            id_document_held=False,
            actor=self.aygun,
        )
        self.tural = ReceptionService.register_walk_in(
            fin_code="",
            first_name="Tural",
            last_name="Həsənov",
            company=self.company,
            visit_type=courier,
            id_document_held=False,
            actor=self.elcin,
        )
        log_action(action="TicketCreated", actor=self.desk, source="domain_event")
        self.url = reverse("erp:audit")

    def test_admin_sees_which_receptionist_checked_in_which_guest(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        times = [row["at"] for row in rows]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertIn(Role.RECEPTION, {row["role"] for row in rows})
        self.assertIn(Role.SERVICE_DESK, {row["role"] for row in rows})
        by_guest = {
            row["object"]: row["actor"]
            for row in rows
            if row["action"] == "Qəbul etdi"
        }
        self.assertEqual(by_guest["Nigar Əliyeva · Ryumka MMC"], "Aygün Məmmədova")
        self.assertEqual(by_guest["Tural Həsənov · Ryumka MMC"], "Elçin Quliyev")
        self.assertNotContains(response, 'id="audit-reception"')
        self.assertContains(response, 'id="audit-log"')
        self.assertContains(response, 'href="/erp/audit/"')

    def test_role_filter_shows_only_that_department(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url + "?role=reception")
        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        self.assertTrue(rows)
        self.assertTrue(all(row["role"] == Role.RECEPTION for row in rows))
        self.assertNotContains(response, "Ticket yaratdı")
        self.assertContains(response, "Aygün Məmmədova")

    def test_domain_check_in_is_not_shown_twice(self):
        log_action(
            action=VISITOR_CHECKED_IN,
            actor=self.aygun,
            entity=self.nigar,
            new_values={"visit_id": self.nigar.pk, "entity_model": "visit"},
            source="domain_event",
        )
        logs = list(AuditLog.objects.filter(entity_id=self.nigar.pk))
        actions = [log.action for log in visible_logs(logs)]
        self.assertIn("visit.check_in", actions)
        self.assertNotIn(VISITOR_CHECKED_IN, actions)

    def test_impersonated_admin_still_sees_one_timeline(self):
        """Case C: Admin during Service Desk preview retains audit (impersonator gate)."""
        from apps.accounts.impersonation import SESSION_IMPERSONATOR_ID, get_impersonator
        from apps.erp.it_access import can_access_erp_audit

        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:switch_role", args=[Role.SERVICE_DESK]))
        session = self.client.session
        self.assertEqual(session.get(SESSION_IMPERSONATOR_ID), self.admin.pk)
        # Effective user is desk; gate still true via impersonator.
        self.assertEqual(self.client.session.get("_auth_user_id"), str(self.desk.pk))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        times = [row["at"] for row in rows]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertIn(Role.RECEPTION, {row["role"] for row in rows})
        self.assertIn(Role.SERVICE_DESK, {row["role"] for row in rows})
        self.assertContains(response, 'href="/erp/audit/"')
        self.assertContains(response, 'id="audit-log"')
        # Policy: Admin preview keeps audit.view authority on the controlling Admin.
        request = response.wsgi_request
        self.assertTrue(can_access_erp_audit(request.user, request))
        self.assertEqual(get_impersonator(request).pk, self.admin.pk)

    def test_ordinary_service_desk_cannot_open_audit(self):
        """Case A: ordinary Service Desk opening /erp/audit/ is soft-denied."""
        from apps.accounts.test_utils import assert_soft_denied
        from apps.erp.it_access import can_access_erp_audit

        self.assertFalse(can_access_erp_audit(self.desk))
        self.client.force_login(self.desk)
        resp = self.client.get(self.url)
        assert_soft_denied(
            self,
            self.client,
            resp,
            self.desk,
            expected_url=reverse("erp:helpdesk_dashboard"),
            protected_markers=('id="audit-log"',),
        )

    def test_admin_audit_normal_then_preview_then_exit(self):
        """Cases B+D: Admin normal access; exit preview restores Admin context."""
        from apps.accounts.impersonation import SESSION_IMPERSONATOR_ID

        # B — Admin normal mode
        self.client.force_login(self.admin)
        normal = self.client.get(self.url)
        self.assertEqual(normal.status_code, 200)
        self.assertContains(normal, 'id="audit-log"')
        self.assertIsNone(self.client.session.get(SESSION_IMPERSONATOR_ID))

        # Enter Service Desk preview (Case C covered above); then D — exit.
        self.client.post(reverse("accounts:switch_role", args=[Role.SERVICE_DESK]))
        self.assertEqual(self.client.session.get(SESSION_IMPERSONATOR_ID), self.admin.pk)
        preview = self.client.get(self.url)
        self.assertEqual(preview.status_code, 200)

        stop = self.client.post(reverse("accounts:stop_role_preview"))
        self.assertEqual(stop.status_code, 302)
        self.assertIsNone(self.client.session.get(SESSION_IMPERSONATOR_ID))
        restored = self.client.get("/erp/", follow=True)
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.request["PATH_INFO"], reverse("erp:it_dashboard"))
        self.assertNotContains(restored, "Adminə qayıt")
        again = self.client.get(self.url)
        self.assertEqual(again.status_code, 200)
        self.assertContains(again, 'id="audit-log"')

    def test_receptionist_cannot_open_audit(self):
        from apps.accounts.test_utils import assert_soft_denied

        self.client.force_login(self.aygun)
        resp = self.client.get(self.url)
        assert_soft_denied(
            self,
            self.client,
            resp,
            self.aygun,
            expected_url=reverse("erp:reception"),
            protected_markers=('id="audit-log"', 'href="/erp/audit/"'),
        )
        home = self.client.get(reverse("erp:reception"))
        self.assertNotContains(home, 'href="/erp/audit/"')

    def test_desk_cannot_acquire_preview_privilege(self):
        """Ordinary desk cannot start role preview to gain audit."""
        from apps.accounts.impersonation import SESSION_IMPERSONATOR_ID
        from apps.accounts.test_utils import assert_soft_denied

        self.client.force_login(self.desk)
        start = self.client.post(reverse("accounts:switch_role", args=[Role.ADMIN]))
        assert_soft_denied(
            self,
            self.client,
            start,
            self.desk,
            expected_url=reverse("erp:helpdesk_dashboard"),
        )
        self.assertIsNone(self.client.session.get(SESSION_IMPERSONATOR_ID))
        denied = self.client.get(self.url)
        assert_soft_denied(
            self,
            self.client,
            denied,
            self.desk,
            expected_url=reverse("erp:helpdesk_dashboard"),
            protected_markers=('id="audit-log"',),
        )
