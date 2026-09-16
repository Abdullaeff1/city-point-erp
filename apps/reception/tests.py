from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.reception.models import Guest, GuestVisit, VisitStatus, VisitorType, mask_fin, normalize_fin
from apps.reception.services import ReceptionService, pre_register_visit
from apps.residents.models import ResidentCompany, ResidentEmployee
from apps.rbac.services import seed_rbac_catalog, user_has_permission


User = get_user_model()


class FinHelpersTests(TestCase):
    def test_normalize_and_mask(self):
        self.assertEqual(normalize_fin(" 7a3-b2c "), "7A3B2C")
        self.assertEqual(mask_fin("7A3B2C1D2K"), "7A3****2K")


class ReceptionServiceTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.company = ResidentCompany.objects.create(name="Test Co", slug="test-co", status="active")
        self.host = ResidentEmployee.objects.create(
            company=self.company, full_name="Host Person", is_active=True
        )
        self.other = ResidentCompany.objects.create(name="Other", slug="other", status="active")
        self.other_host = ResidentEmployee.objects.create(
            company=self.other, full_name="Other Host", is_active=True
        )
        self.vtype = VisitorType.objects.create(code="meeting", name="Meeting")
        self.user = User.objects.create_user(
            username="reception_test",
            email="reception@test.az",
            password="x",
            role=Role.RECEPTION,
        )

    def test_walk_in_requires_id_or_override(self):
        with self.assertRaises(DomainError):
            ReceptionService.register_walk_in(
                fin_code="7A3B2C1D2K",
                first_name="Ali",
                last_name="Veli",
                company=self.company,
                host=self.host,
                visit_type=self.vtype,
                id_document_held=False,
                actor=self.user,
            )
        visit = ReceptionService.register_walk_in(
            fin_code="7A3B2C1D2K",
            first_name="Ali",
            last_name="Veli",
            company=self.company,
            host=self.host,
            visit_type=self.vtype,
            id_document_held=True,
            actor=self.user,
        )
        self.assertEqual(visit.status, VisitStatus.INSIDE)
        self.assertTrue(visit.check_in_at)
        self.assertTrue(hasattr(visit, "visitor_access"))

    def test_fin_reuses_guest(self):
        g1 = ReceptionService.find_or_create_guest(
            fin_code="ABC12345XY", first_name="A", last_name="B", actor=self.user
        )
        g2 = ReceptionService.find_or_create_guest(
            fin_code="abc12345xy", first_name="A", last_name="B", actor=self.user
        )
        self.assertEqual(g1.pk, g2.pk)

    def test_host_must_belong_to_company(self):
        with self.assertRaises(DomainError):
            ReceptionService.register_walk_in(
                fin_code="ZZZ11111AA",
                first_name="X",
                last_name="Y",
                company=self.company,
                host=self.other_host,
                id_document_held=True,
                actor=self.user,
            )

    def test_duplicate_inside_blocked(self):
        ReceptionService.register_walk_in(
            fin_code="DUP11111AA",
            first_name="Dup",
            last_name="Guest",
            company=self.company,
            id_document_held=True,
            actor=self.user,
        )
        with self.assertRaises(DomainError):
            ReceptionService.register_walk_in(
                fin_code="DUP11111AA",
                first_name="Dup",
                last_name="Guest",
                company=self.company,
                id_document_held=True,
                actor=self.user,
            )

    def test_prereg_checkin_checkout_cancel(self):
        visit = pre_register_visit(
            company=self.company,
            first_name="Pre",
            last_name="Reg",
            host=self.host,
            visit_type=self.vtype,
        )
        self.assertEqual(visit.status, VisitStatus.PRE_REGISTERED)
        self.assertTrue(visit.invite_code)

        ReceptionService.check_in_visit(
            visit, actor=self.user, fin_code="PRE11111AA", id_document_held=True
        )
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.INSIDE)

        ReceptionService.check_out_visit(visit, actor=self.user, id_returned=True)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.LEFT)
        self.assertTrue(visit.check_out_at)

        visit2 = pre_register_visit(company=self.company, first_name="Cancel", last_name="Me")
        ReceptionService.cancel_visit(visit2, actor=self.user)
        visit2.refresh_from_db()
        self.assertEqual(visit2.status, VisitStatus.CANCELLED)
        with self.assertRaises(DomainError):
            ReceptionService.check_in_visit(visit2, actor=self.user, id_document_held=True)

    def test_checkout_blocks_without_id_return(self):
        visit = ReceptionService.register_walk_in(
            fin_code="IDHOLD01AA",
            first_name="Id",
            last_name="Hold",
            company=self.company,
            id_document_held=True,
            actor=self.user,
        )
        with self.assertRaises(DomainError):
            ReceptionService.check_out_visit(visit, actor=self.user, id_returned=False)
        pending = ReceptionService.check_out_visit(
            visit, actor=self.user, id_returned=False, allow_return_pending=True
        )
        self.assertEqual(pending.status, VisitStatus.RETURN_PENDING)


class ReceptionPermissionTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.reception = User.objects.create_user(
            username="rec_perm", email="r@test.az", password="x", role=Role.RECEPTION
        )
        self.fm = User.objects.create_user(
            username="fm_perm", email="fm@test.az", password="x", role=Role.PROPERTY_FM
        )

    def test_reception_has_granular_perms(self):
        self.assertTrue(user_has_permission(self.reception, "reception.create_visit"))
        self.assertTrue(user_has_permission(self.reception, "reception.view_sensitive_data"))
        self.assertTrue(user_has_permission(self.fm, "reception.view"))
        self.assertFalse(user_has_permission(self.fm, "reception.create_visit"))


class ReceptionAPITests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.client = Client()
        self.user = User.objects.create_user(
            username="api_rec",
            email="api-rec@test.az",
            password="pass12345",
            role=Role.RECEPTION,
        )
        self.company = ResidentCompany.objects.create(name="API Co", slug="api-co", status="active")
        self.client.login(email="api-rec@test.az", password="pass12345")

    def test_today_endpoint(self):
        res = self.client.get("/api/reception/today/")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("stats", data)
        self.assertIn("results", data)
