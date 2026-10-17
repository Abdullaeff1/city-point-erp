"""ACL, conversion, pin, and SVG tests for security floor plans."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.property.models import Building, Floor
from apps.security.models import (
    ConversionStatus,
    DeviceType,
    PlanCategory,
    SecurityDevice,
    SecurityFloorPlan,
)
from apps.security.plan_convert import convert_source_to_svg
from apps.security.services import (
    SecurityPinService,
    SecurityPlanService,
    claim_pending_revisions,
    convert_revision,
)
from apps.security.svg_sanitize import SvgSanitizeError, sanitize_svg

User = get_user_model()
FIXTURE_DXF = Path(__file__).resolve().parents[1] / "fixtures" / "sample_floor.dxf"


def _ensure_fixture_dxf() -> Path:
    if not FIXTURE_DXF.exists():
        from apps.security.fixtures.build_sample_dxf import main

        main()
    return FIXTURE_DXF


class SecurityFloorPlanTests(TestCase):
    def setUp(self):
        from django.conf import settings
        from pathlib import Path as P
        import tempfile

        self._tmpdir = tempfile.mkdtemp(prefix="cp_priv_")
        settings.PRIVATE_MEDIA_ROOT = P(self._tmpdir)
        from apps.security.storage import private_plan_storage

        private_plan_storage.location = str(settings.PRIVATE_MEDIA_ROOT)

        self.building = Building.objects.create(name="CP Test", code="CPT")
        self.floor = Floor.objects.create(building=self.building, code="L1", name="Level 1")
        self.security = User.objects.create_user(
            username="sec_plans",
            email="sec_plans@test.az",
            password="Pass12345!",
            role=Role.SECURITY,
        )
        self.admin = User.objects.create_user(
            username="admin_plans",
            email="admin_plans@test.az",
            password="Pass12345!",
            role=Role.ADMIN,
        )
        self.management = User.objects.create_user(
            username="mgmt_plans",
            email="mgmt_plans@test.az",
            password="Pass12345!",
            role=Role.MANAGEMENT,
        )
        self.reception = User.objects.create_user(
            username="rec_plans",
            email="rec_plans@test.az",
            password="Pass12345!",
            role=Role.RECEPTION,
        )
        self.resident = User.objects.create_user(
            username="res_plans",
            email="res_plans@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        self.client = Client()
        self.dxf_bytes = _ensure_fixture_dxf().read_bytes()

    def _upload_dxf(self, user=None):
        user = user or self.security
        uploaded = SimpleUploadedFile(
            "floor.dxf", self.dxf_bytes, content_type="application/dxf"
        )
        return SecurityPlanService.create_plan_with_upload(
            user=user,
            title="L1 Cameras",
            floor=self.floor,
            category=PlanCategory.CAMERAS,
            uploaded=uploaded,
        )

    def test_security_and_admin_can_view_plans_page(self):
        for user in (self.security, self.admin, self.management):
            self.client.force_login(user)
            resp = self.client.get(reverse("security:plans"))
            self.assertEqual(resp.status_code, 200, user.role)

    def test_reception_and_resident_denied(self):
        for user in (self.reception, self.resident):
            self.client.force_login(user)
            resp = self.client.get(reverse("security:plans"))
            self.assertIn(resp.status_code, (302, 403), user.role)

    def test_management_cannot_upload(self):
        self.client.force_login(self.management)
        resp = self.client.post(
            reverse("security:plan_upload"),
            {
                "title": "X",
                "floor": self.floor.pk,
                "category": PlanCategory.MIXED,
                "source_file": SimpleUploadedFile("a.dxf", self.dxf_bytes),
            },
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(SecurityFloorPlan.objects.count(), 0)

    def test_dxf_upload_pending_then_convert_ready(self):
        plan, rev = self._upload_dxf()
        self.assertEqual(rev.conversion_status, ConversionStatus.PENDING)
        claimed = claim_pending_revisions(limit=5)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].pk, rev.pk)
        status = convert_revision(claimed[0])
        rev.refresh_from_db()
        self.assertEqual(status, ConversionStatus.READY)
        self.assertEqual(rev.conversion_status, ConversionStatus.READY)
        self.assertTrue(rev.svg_file)
        # Parallel claim should not re-grab processing/ready
        self.assertEqual(claim_pending_revisions(limit=5), [])

    def test_dwg_without_converter_unsupported(self):
        uploaded = SimpleUploadedFile("floor.dwg", b"fake-dwg-bytes", content_type="application/acad")
        with override_settings(SECURITY_DWG_CONVERTER=""):
            plan, rev = SecurityPlanService.create_plan_with_upload(
                user=self.security,
                title="DWG plan",
                floor=self.floor,
                category=PlanCategory.MIXED,
                uploaded=uploaded,
            )
            claimed = claim_pending_revisions(limit=1)[0]
            status = convert_revision(claimed)
            rev.refresh_from_db()
            self.assertEqual(status, ConversionStatus.UNSUPPORTED)
            self.assertTrue(rev.source_file)
            self.assertIn("DWG", rev.conversion_error)

    def test_corrupt_dxf_failed_keeps_original(self):
        uploaded = SimpleUploadedFile("bad.dxf", b"not-a-dxf", content_type="application/dxf")
        plan, rev = SecurityPlanService.create_plan_with_upload(
            user=self.security,
            title="Bad",
            floor=self.floor,
            category=PlanCategory.MIXED,
            uploaded=uploaded,
        )
        claimed = claim_pending_revisions(limit=1)[0]
        status = convert_revision(claimed)
        rev.refresh_from_db()
        self.assertEqual(status, ConversionStatus.FAILED)
        self.assertTrue(rev.source_file)
        self.assertFalse(bool(rev.conversion_error and "Traceback" in rev.conversion_error))
        self.assertFalse("/app/" in (rev.conversion_error or ""))

    def test_activate_and_svg_img_endpoint(self):
        plan, rev = self._upload_dxf()
        convert_revision(claim_pending_revisions(limit=1)[0])
        rev.refresh_from_db()
        SecurityPlanService.activate_revision(user=self.security, revision=rev)
        rev.refresh_from_db()
        self.assertTrue(rev.is_active)

        self.client.force_login(self.management)
        svg_url = reverse("security:plan_svg", kwargs={"pk": plan.pk, "revision_id": rev.pk})
        resp = self.client.get(svg_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"].split(";")[0], "image/svg+xml")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")

        self.client.logout()
        resp = self.client.get(svg_url)
        self.assertIn(resp.status_code, (302, 403))

    def test_source_download_attachment(self):
        plan, rev = self._upload_dxf()
        status = convert_revision(claim_pending_revisions(limit=1)[0])
        self.assertEqual(status, ConversionStatus.READY)
        rev.refresh_from_db()
        # Source download allowed for portal viewers even before activate.
        self.client.force_login(self.security)
        url = reverse(
            "security:plan_source_download",
            kwargs={"pk": plan.pk, "revision_id": rev.pk},
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp.get("Content-Disposition", ""))

        self.client.force_login(self.reception)
        resp = self.client.get(url)
        self.assertIn(resp.status_code, (302, 403))

    def test_pin_rules_and_no_auto_copy(self):
        plan, rev = self._upload_dxf()
        convert_revision(claim_pending_revisions(limit=1)[0])
        rev.refresh_from_db()
        SecurityPlanService.activate_revision(user=self.security, revision=rev)
        cam = SecurityDevice.objects.create(
            name="Cam-1", device_type=DeviceType.CAMERA, ip_address="10.0.0.1"
        )
        sensor = SecurityDevice.objects.create(
            name="Sens-1", device_type=DeviceType.SENSOR
        )
        pin, _ = SecurityPinService.upsert_pin(
            user=self.security, revision=rev, device=cam, x_pct=10, y_pct=20
        )
        self.assertEqual(pin.x_pct, Decimal("10"))
        with self.assertRaises(DomainError):
            SecurityPinService.upsert_pin(
                user=self.security, revision=rev, device=sensor, x_pct=50, y_pct=50
            )
        with self.assertRaises(DomainError):
            SecurityPinService.upsert_pin(
                user=self.security, revision=rev, device=cam, x_pct=150, y_pct=10
            )
        # New revision does not copy pins
        uploaded = SimpleUploadedFile("floor2.dxf", self.dxf_bytes)
        rev2 = SecurityPlanService.upload_revision(
            user=self.security, plan=plan, uploaded=uploaded
        )
        self.assertEqual(rev2.pins.count(), 0)
        self.assertEqual(rev.pins.count(), 1)

    def test_management_cannot_place_pin(self):
        plan, rev = self._upload_dxf()
        convert_revision(claim_pending_revisions(limit=1)[0])
        rev.refresh_from_db()
        SecurityPlanService.activate_revision(user=self.security, revision=rev)
        cam = SecurityDevice.objects.create(name="Cam-2", device_type=DeviceType.CAMERA)
        with self.assertRaises(DomainError):
            SecurityPinService.upsert_pin(
                user=self.management, revision=rev, device=cam, x_pct=1, y_pct=1
            )

    def test_svg_sanitize_blocks_script(self):
        with self.assertRaises(SvgSanitizeError):
            sanitize_svg('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
        with self.assertRaises(SvgSanitizeError):
            sanitize_svg(
                '<svg xmlns="http://www.w3.org/2000/svg"><rect onclick="x()" width="1" height="1"/></svg>'
            )
        ok = sanitize_svg(
            '<svg xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="10" height="10"/></svg>'
        )
        self.assertIn("rect", ok)

    def test_ezdxf_fixture_converts(self):
        path = _ensure_fixture_dxf()
        svg, tool, ver = convert_source_to_svg(path, "dxf")
        self.assertTrue(svg.startswith(b"<") or b"svg" in svg[:200].lower())
        self.assertEqual(tool, "ezdxf")
        self.assertTrue(ver)

    def test_reject_bad_extension(self):
        uploaded = SimpleUploadedFile("x.pdf", b"%PDF", content_type="application/pdf")
        with self.assertRaises(DomainError):
            SecurityPlanService.create_plan_with_upload(
                user=self.security,
                title="bad",
                floor=self.floor,
                category=PlanCategory.MIXED,
                uploaded=uploaded,
            )
