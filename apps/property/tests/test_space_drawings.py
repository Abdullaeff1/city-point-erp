import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.comms.models import Notification
from apps.property.drawings import (
    create_space_drawing,
    decide_access_request,
    request_drawing_access,
    user_can_manage_space_drawings,
)
from apps.property.management.commands.import_space_drawings import load_mapping
from apps.property.models import (
    Building,
    Floor,
    Space,
    SpaceDrawing,
    SpaceDrawingAccessStatus,
    SpaceDrawingKind,
)
from apps.residents.models import ResidentCompany

User = get_user_model()


class SpaceDrawingPermissionTests(TestCase):
    def setUp(self):
        building = Building.objects.create(code="CP", name="City Point")
        self.floor = Floor.objects.create(building=building, code="F08", name="8")
        self.company = ResidentCompany.objects.create(
            name="ASBC Draw", slug="asbc-draw", portal_active=True
        )
        self.space = Space.objects.create(
            code="CP-DRAW-1",
            name="Draw Office",
            floor=self.floor,
            resident=self.company,
            area_m2="100",
        )
        self.admin = User.objects.create_user(
            username="adm-d", email="adm-d@test.az", password="Pass12345!", role=Role.ADMIN
        )
        self.fm = User.objects.create_user(
            username="fm-d", email="fm-d@test.az", password="Pass12345!", role=Role.PROPERTY_FM
        )
        self.mgmt = User.objects.create_user(
            username="mgmt-d", email="mgmt-d@test.az", password="Pass12345!", role=Role.MANAGEMENT
        )
        self.reception = User.objects.create_user(
            username="rec-d", email="rec-d@test.az", password="Pass12345!", role=Role.RECEPTION
        )
        self.resident = User.objects.create_user(
            username="res-d",
            email="res-d@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        ensure_portal_membership(self.resident, self.company)
        self.drawing = create_space_drawing(
            space=self.space,
            uploaded_file=SimpleUploadedFile("plan.dxf", b"0\nSECTION\n", content_type="application/dxf"),
            kind=SpaceDrawingKind.DXF,
            uploaded_by=self.admin,
            build_svg=False,
        )
        self.client = Client()

    def test_manager_roles(self):
        self.assertTrue(user_can_manage_space_drawings(self.admin))
        self.assertTrue(user_can_manage_space_drawings(self.fm))
        self.assertTrue(user_can_manage_space_drawings(self.mgmt))
        self.assertFalse(user_can_manage_space_drawings(self.reception))
        self.assertFalse(user_can_manage_space_drawings(self.resident))

    def test_erp_dwg_tab_admin_and_mgmt_ok(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("erp:space_detail", args=[self.space.code]), {"tab": "dwg"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "plan.dxf")
        self.assertTrue(resp.context["can_manage_drawings"])
        self.assertNotContains(resp, "data-svg-preview")

        self.client.force_login(self.mgmt)
        resp2 = self.client.get(reverse("erp:space_detail", args=[self.space.code]), {"tab": "dwg"})
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.context["can_manage_drawings"])
        self.assertEqual(resp2.context["tab"], "dwg")
        self.assertContains(resp2, "plan.dxf")
        self.assertNotContains(resp2, "data-svg-preview")

    def test_reception_cannot_download(self):
        self.client.force_login(self.reception)
        resp = self.client.get(reverse("erp:space_drawing_download", args=[self.drawing.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_admin_download_ok(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("erp:space_drawing_download", args=[self.drawing.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp.get("Content-Disposition", ""))


class SpaceDrawingAccessWorkflowTests(TestCase):
    def setUp(self):
        building = Building.objects.create(code="CP2", name="City Point 2")
        floor = Floor.objects.create(building=building, code="F07", name="7")
        self.company = ResidentCompany.objects.create(
            name="Co Draw", slug="co-draw", portal_active=True
        )
        self.space = Space.objects.create(
            code="CP-DRAW-2", name="O2", floor=floor, resident=self.company, area_m2="50"
        )
        self.admin = User.objects.create_user(
            username="adm2", email="adm2@test.az", password="Pass12345!", role=Role.ADMIN
        )
        self.mgmt = User.objects.create_user(
            username="mgmt2", email="mgmt2@test.az", password="Pass12345!", role=Role.MANAGEMENT
        )
        self.resident = User.objects.create_user(
            username="res2",
            email="res2@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        ensure_portal_membership(self.resident, self.company)
        self.drawing = create_space_drawing(
            space=self.space,
            uploaded_file=SimpleUploadedFile("t.png", b"\x89PNG\r\n", content_type="image/png"),
            kind=SpaceDrawingKind.TECHNICAL_PLAN,
            uploaded_by=self.admin,
            build_svg=False,
        )
        self.client = Client()

    def test_request_notifies_admin_and_mgmt(self):
        before_admin = Notification.objects.filter(user=self.admin).count()
        before_mgmt = Notification.objects.filter(user=self.mgmt).count()
        req = request_drawing_access(user=self.resident, drawing=self.drawing)
        self.assertEqual(req.status, SpaceDrawingAccessStatus.PENDING)
        self.assertGreater(Notification.objects.filter(user=self.admin).count(), before_admin)
        self.assertGreater(Notification.objects.filter(user=self.mgmt).count(), before_mgmt)
        note = Notification.objects.filter(user=self.mgmt).order_by("-id").first()
        self.assertIn("space_drawing_access:", note.event_key)

    def test_mgmt_approve_allows_portal_download_then_expiry(self):
        req = request_drawing_access(user=self.resident, drawing=self.drawing)
        decide_access_request(req=req, actor=self.mgmt, approve=True, ttl_hours=72)
        req.refresh_from_db()
        self.assertTrue(req.is_download_allowed)

        self.client.force_login(self.resident)
        resp = self.client.get(reverse("portal:drawing_download", args=[self.drawing.pk]))
        self.assertEqual(resp.status_code, 200)

        req.expires_at = timezone.now() - timedelta(hours=1)
        req.save(update_fields=["expires_at"])
        resp2 = self.client.get(reverse("portal:drawing_download", args=[self.drawing.pk]))
        self.assertEqual(resp2.status_code, 403)

    def test_portal_request_post_and_download_ui(self):
        self.client.force_login(self.resident)
        resp = self.client.post(reverse("portal:drawing_access_request", args=[self.drawing.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            self.drawing.access_requests.filter(
                user=self.resident, status=SpaceDrawingAccessStatus.PENDING
            ).exists()
        )

        list_resp = self.client.get(
            reverse("portal:space_detail", args=[self.space.code]), {"tab": "technical_plan"}
        )
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, "Gözləyir")

        req = self.drawing.access_requests.get(user=self.resident)
        decide_access_request(req=req, actor=self.admin, approve=True, ttl_hours=72)
        approved = self.client.get(
            reverse("portal:space_detail", args=[self.space.code]), {"tab": "technical_plan"}
        )
        self.assertContains(approved, "Yüklə")
        self.assertContains(approved, reverse("portal:drawing_download", args=[self.drawing.pk]))


class ImportSpaceDrawingsTests(TestCase):
    def test_load_mapping_and_skip_unmapped(self):
        building = Building.objects.create(code="CP3", name="CP3")
        floor = Floor.objects.create(building=building, code="F01", name="1")
        company = ResidentCompany.objects.create(name="Imp", slug="imp-co", portal_active=True)
        space = Space.objects.create(
            code="CP-IMP-1", name="Imp", floor=floor, resident=company, area_m2="10"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            office = root / "F01" / "F01_Ofis_01"
            office.mkdir(parents=True)
            (office / "F01_Ofis_01.json").write_text(
                '{"id":"F01_Ofis_01","dxf_file":"F01_Ofis_01.dxf","preview_file":"F01_Ofis_01.png"}',
                encoding="utf-8",
            )
            (office / "F01_Ofis_01.dxf").write_bytes(b"0\nSECTION\n")
            (office / "F01_Ofis_01.png").write_bytes(b"\x89PNG\r\n")
            map_path = root / "space_drawing_map.csv"
            map_path.write_text("package_id,space_code\nF01_Ofis_01,CP-IMP-1\n", encoding="utf-8")
            mapping = load_mapping(map_path)
            self.assertEqual(mapping["F01_Ofis_01"], "CP-IMP-1")
            call_command("import_space_drawings", root=str(root), map_path=str(map_path))
            self.assertEqual(SpaceDrawing.objects.filter(space=space).count(), 2)

            # unmapped package skipped
            office2 = root / "F01" / "F01_Ofis_99"
            office2.mkdir(parents=True)
            (office2 / "F01_Ofis_99.json").write_text(
                '{"id":"F01_Ofis_99","dxf_file":"F01_Ofis_99.dxf"}', encoding="utf-8"
            )
            (office2 / "F01_Ofis_99.dxf").write_bytes(b"0\n")
            call_command("import_space_drawings", root=str(root), map_path=str(map_path))
            self.assertFalse(SpaceDrawing.objects.filter(package_id="F01_Ofis_99").exists())
