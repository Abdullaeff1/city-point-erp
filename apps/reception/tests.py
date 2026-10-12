from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.reception.models import (
    Guest,
    GuestVisit,
    VisitStatus,
    VisitorAccess,
    VisitorAccessStatus,
    VisitorType,
    mask_fin,
    normalize_fin,
)
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
        self.vtype, _ = VisitorType.objects.get_or_create(
            code="meeting", defaults={"name": "İclas üçün", "sort_order": 50}
        )
        self.user = User.objects.create_user(
            username="reception_test",
            email="reception@test.az",
            password="x",
            role=Role.RECEPTION,
        )

    def test_serial_required_when_id_held(self):
        with self.assertRaises(DomainError) as ctx:
            ReceptionService.register_walk_in(
                fin_code="",
                first_name="Ali",
                last_name="Veli",
                company=self.company,
                id_document_held=True,
                guest_card_number="GC-1",
                actor=self.user,
            )
        self.assertIn("Seriya", str(ctx.exception))

    def test_walk_in_courier_without_serial_ok(self):
        """Kuryer: seriya boş, vəsiqə saxlanılmır — yalnız ad/soyad/şirkət."""
        courier, _ = VisitorType.objects.get_or_create(
            code="courier", defaults={"name": "Kuryer", "sort_order": 10}
        )
        visit = ReceptionService.register_walk_in(
            fin_code="",
            first_name="Kuryer",
            last_name="Ali",
            company=self.company,
            host=self.host,
            visit_type=courier,
            id_document_held=False,
            notes="Kuryer",
            actor=self.user,
        )
        self.assertEqual(visit.status, VisitStatus.INSIDE)
        self.assertEqual(visit.guest.fin_code, "")
        self.assertFalse(visit.id_document_held)
        self.assertEqual(visit.visit_type.code, "courier")

    def test_walk_in_without_id_ok(self):
        visit = ReceptionService.register_walk_in(
            fin_code="7A3B2C1D2K",
            first_name="Ali",
            last_name="Veli",
            company=self.company,
            host=self.host,
            visit_type=self.vtype,
            id_document_held=False,
            actor=self.user,
        )
        self.assertEqual(visit.status, VisitStatus.INSIDE)
        self.assertTrue(visit.check_in_at)
        self.assertFalse(visit.id_document_held)
        self.assertFalse(VisitorAccess.objects.filter(visit=visit).exists())

    def test_walk_in_with_id_issues_guest_card(self):
        with self.assertRaises(DomainError):
            ReceptionService.register_walk_in(
                fin_code="7A3B2C1D2K",
                first_name="Ali",
                last_name="Veli",
                company=self.company,
                host=self.host,
                visit_type=self.vtype,
                id_document_held=True,
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
            guest_card_number="GK-1001",
            actor=self.user,
        )
        self.assertEqual(visit.status, VisitStatus.INSIDE)
        self.assertTrue(visit.id_document_held)
        self.assertTrue(hasattr(visit, "visitor_access"))
        self.assertEqual(visit.visitor_access.status, VisitorAccessStatus.ACTIVE)
        self.assertEqual(visit.visitor_access.credential, "GK-1001")

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
                guest_card_number="GK-1",
                actor=self.user,
            )

    def test_duplicate_inside_blocked(self):
        ReceptionService.register_walk_in(
            fin_code="DUP11111AA",
            first_name="Dup",
            last_name="Guest",
            company=self.company,
            id_document_held=True,
            guest_card_number="GK-DUP",
            actor=self.user,
        )
        with self.assertRaises(DomainError):
            ReceptionService.register_walk_in(
                fin_code="DUP11111AA",
                first_name="Dup",
                last_name="Guest",
                company=self.company,
                id_document_held=True,
                guest_card_number="GK-DUP2",
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
            visit,
            actor=self.user,
            fin_code="PRE11111AA",
            id_document_held=True,
            guest_card_number="GK-PRE",
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
            ReceptionService.check_in_visit(
                visit2, actor=self.user, id_document_held=True, guest_card_number="GK-X"
            )

    def test_checkout_blocks_without_id_return(self):
        visit = ReceptionService.register_walk_in(
            fin_code="IDHOLD01AA",
            first_name="Id",
            last_name="Hold",
            company=self.company,
            id_document_held=True,
            guest_card_number="GK-HOLD",
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


class ReceptionExcelExportTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.client = Client()
        self.user = User.objects.create_user(
            username="rec_xlsx",
            email="rec-xlsx@test.az",
            password="pass12345",
            role=Role.RECEPTION,
        )
        self.company = ResidentCompany.objects.create(
            name="Export Co", slug="export-co", status="active"
        )
        self.vtype, _ = VisitorType.objects.get_or_create(
            code="courier", defaults={"name": "Kuryer", "sort_order": 10}
        )
        self.client.login(email="rec-xlsx@test.az", password="pass12345")
        today = timezone.localdate()
        ReceptionService.register_walk_in(
            fin_code="",
            first_name="Kuryer",
            last_name="Test",
            company=self.company,
            visit_type=self.vtype,
            id_document_held=False,
            notes="Excel test",
            actor=self.user,
        )
        self.today = today

    def test_export_xlsx_today(self):
        from io import BytesIO

        from openpyxl import load_workbook

        res = self.client.get(reverse("erp:reception_export") + f"?range=today&date={self.today.isoformat()}")
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "spreadsheetml.sheet",
            res["Content-Type"],
        )
        self.assertIn(".xlsx", res["Content-Disposition"])
        wb = load_workbook(BytesIO(res.content))
        self.assertEqual(wb.sheetnames, ["Qonaqlar"])
        ws = wb.active
        self.assertEqual(ws["A1"].value, "Qonaqlar hesabatı")
        # row1 title, row2 period, row3 blank, row4 company
        self.assertTrue(str(ws["A4"].value).startswith("Export Co"))
        self.assertEqual(ws["A5"].value, "№")
        self.assertEqual(ws["B5"].value, "Qonaq")
        self.assertEqual(ws["F5"].value, "Gəliş səbəbi")
        self.assertEqual(ws["A6"].value, 1)
        self.assertEqual(ws["B6"].value, "Kuryer Test")
        self.assertEqual(ws["F6"].value, "Kuryer")

    def test_export_xlsx_companies_alpha_one_sheet(self):
        from io import BytesIO

        from openpyxl import load_workbook

        other = ResidentCompany.objects.create(name="Beta Co", slug="beta-co", status="active")
        ReceptionService.register_walk_in(
            fin_code="",
            first_name="Qonaq",
            last_name="Beta",
            company=other,
            visit_type=self.vtype,
            id_document_held=False,
            actor=self.user,
        )
        res = self.client.get(reverse("erp:reception_export") + f"?range=today&date={self.today.isoformat()}")
        wb = load_workbook(BytesIO(res.content))
        self.assertEqual(wb.sheetnames, ["Qonaqlar"])
        ws = wb.active
        # Alpha order: Beta Co before Export Co (row4 after title/period/blank)
        self.assertTrue(str(ws["A4"].value).startswith("Beta Co"))
        self.assertEqual(ws["B6"].value, "Qonaq Beta")
        found_export = False
        for r in range(1, ws.max_row + 1):
            val = ws.cell(r, 1).value
            if isinstance(val, str) and val.startswith("Export Co"):
                found_export = True
                self.assertEqual(ws.cell(r + 2, 2).value, "Kuryer Test")
                self.assertEqual(ws.cell(r + 2, 1).value, 1)
                break
        self.assertTrue(found_export)

    def test_export_xlsx_week_range(self):
        res = self.client.get(reverse("erp:reception_export") + "?range=week")
        self.assertEqual(res.status_code, 200)
        self.assertIn(".xlsx", res["Content-Disposition"])

    def test_export_page_shows_excel_controls(self):
        res = self.client.get(reverse("erp:reception") + "?range=month")
        self.assertEqual(res.status_code, 200)
        body = res.content.decode("utf-8", "replace")
        self.assertIn("Excel yüklə", body)
        self.assertIn("Bu həftə", body)
        self.assertIn("Bu ay", body)
        self.assertIn("Tarix aralığı", body)
