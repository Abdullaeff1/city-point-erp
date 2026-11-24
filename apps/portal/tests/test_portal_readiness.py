"""Resident portal readiness — scope, invoices, guests, cards, notifications."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.portal_scope import MODE_ALL, MODE_SINGLE
from apps.accounts.test_utils import ensure_portal_membership, ensure_portal_memberships
from apps.accounting.services import seed_minimal_coa
from apps.billing.models import Charge, ChargeSource
from apps.billing.services import confirm_invoice, generate_invoice_from_charges
from apps.comms.links import user_notifications
from apps.comms.models import Notification
from apps.parties.resolvers import party_for_company
from apps.property.drawings import create_space_drawing, decide_access_request, request_drawing_access
from apps.property.models import Building, Floor, Space, SpaceDrawingKind
from apps.reception.models import Guest, GuestVisit, VisitStatus
from apps.residents.models import AccessLevel, CardOrderStatus, ResidentCompany
from apps.residents.services import create_employee_card_order
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy

User = get_user_model()

PORTAL_NAV = [
    "portal:home",
    "portal:company_profile",
    "portal:spaces",
    "portal:requests_active",
    "portal:requests_history",
    "portal:alerts",
    "portal:employees",
    "portal:guests",
    "portal:announcements",
    "portal:documents",
    "portal:invoices",
    "portal:building_procedures",
    "portal:user_guide",
    "portal:request_new",
]


class PortalNavAndScopeTests(TestCase):
    def setUp(self):
        self.c1 = ResidentCompany.objects.create(name="Nav A", slug="nav-a", portal_active=True)
        self.c2 = ResidentCompany.objects.create(name="Nav B", slug="nav-b", portal_active=True)
        self.single = User.objects.create_user(
            username="nav-single",
            email="nav-single@test.az",
            password="x",
            role=Role.RESIDENT_USER,
        )
        self.multi = User.objects.create_user(
            username="nav-multi",
            email="nav-multi@test.az",
            password="x",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_membership(self.single, self.c1)
        ensure_portal_memberships(self.multi, [self.c1, self.c2])
        self.client = Client()

    def test_single_company_all_nav_200(self):
        self.client.force_login(self.single)
        for name in PORTAL_NAV:
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 200, name)

    def test_multi_company_a_b_and_all(self):
        self.client.force_login(self.multi)
        self.assertEqual(
            self.client.get(reverse("portal:home")).status_code,
            302,
        )
        for choice, mode in (
            (str(self.c1.pk), MODE_SINGLE),
            (str(self.c2.pk), MODE_SINGLE),
            ("all", MODE_ALL),
        ):
            self.client.post(reverse("portal:choose_companies"), {"choice": choice})
            self.assertEqual(self.client.session["portal_scope_mode"], mode)
            for name in PORTAL_NAV:
                resp = self.client.get(reverse(name))
                self.assertEqual(resp.status_code, 200, f"{choice}:{name}")
            profile = self.client.get(reverse("portal:company_profile"))
            if choice == "all":
                self.assertContains(profile, "Nav A")
                self.assertContains(profile, "Nav B")
            elif choice == str(self.c1.pk):
                self.assertContains(profile, "Nav A")
                self.assertNotContains(profile, "Nav B")


class PortalInvoiceTotalsTests(TestCase):
    def setUp(self):
        seed_minimal_coa()
        self.company = ResidentCompany.objects.create(
            name="Inv Co", slug="inv-co", portal_active=True
        )
        self.party = party_for_company(self.company, ensure=True)
        self.user = User.objects.create_user(
            username="inv-u",
            email="inv-u@test.az",
            password="x",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_membership(self.user, self.company)
        self.client = Client()
        self.client.force_login(self.user)

    def test_totals_span_pages_and_keep_currencies_separate(self):
        # 51 ISSUED invoices → 2 pages at 50/page; totals must include page 2.
        for i in range(51):
            currency = "AZN" if i < 40 else "USD"
            amount = Decimal("10.00") if currency == "AZN" else Decimal("5.00")
            charge = Charge.objects.create(
                party=self.party,
                source=ChargeSource.RENT,
                description=f"row-{i}",
                amount=amount,
                currency=currency,
            )
            inv = generate_invoice_from_charges(
                self.party, [charge.pk], apply_vat=False
            )
            if inv.currency != currency:
                inv.currency = currency
                inv.save(update_fields=["currency"])
            confirm_invoice(inv)

        page1 = self.client.get(reverse("portal:invoices"))
        self.assertEqual(page1.status_code, 200)
        totals = page1.context["currency_totals"]
        self.assertEqual(totals["AZN"]["open"], Decimal("400.00"))
        self.assertEqual(totals["USD"]["open"], Decimal("55.00"))
        self.assertTrue(page1.context["page_obj"].has_other_pages)
        page2 = self.client.get(reverse("portal:invoices") + "?page=2")
        self.assertEqual(page2.context["currency_totals"]["AZN"]["open"], Decimal("400.00"))
        self.assertEqual(page2.context["currency_totals"]["USD"]["open"], Decimal("55.00"))
        self.assertContains(page1, "Rəsmi PDF")


class PortalInvoiceDetailAndOfficialPdfTests(TestCase):
    def setUp(self):
        seed_minimal_coa()
        self.c1 = ResidentCompany.objects.create(name="Det A", slug="det-a", portal_active=True)
        self.c2 = ResidentCompany.objects.create(name="Det B", slug="det-b", portal_active=True)
        self.p1 = party_for_company(self.c1, ensure=True)
        self.p2 = party_for_company(self.c2, ensure=True)
        self.user = User.objects.create_user(
            username="det-u",
            email="det-u@test.az",
            password="x",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_memberships(self.user, [self.c1, self.c2])
        self.client = Client()
        self.client.force_login(self.user)
        self.accountant = User.objects.create_user(
            username="det-acc",
            email="det-acc@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.manager = User.objects.create_user(
            username="det-mgmt",
            email="det-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )

    def _issued(self, party, amount=Decimal("100.00"), desc="rent"):
        charge = Charge.objects.create(
            party=party,
            source=ChargeSource.RENT,
            description=desc,
            amount=amount,
            currency="AZN",
        )
        inv = generate_invoice_from_charges(party, [charge.pk], apply_vat=False)
        confirm_invoice(inv)
        return inv

    def test_detail_lines_payments_and_scope(self):
        from apps.billing.services import record_payment
        from apps.workflows.services import ApprovalService

        inv_a = self._issued(self.p1, Decimal("1000.00"), "line-A")
        inv_b = self._issued(self.p2, Decimal("200.00"), "line-B-SECRET")
        req = ApprovalService.request(
            workflow_code="finance.payment",
            requested_by=self.accountant,
            entity=inv_a,
            payload={
                "invoice_id": inv_a.pk,
                "invoice_code": inv_a.code,
                "amount": "400.00",
                "method": "bank",
                "reference": "DET-400",
            },
        )
        ApprovalService.decide(req, approved=True, decided_by=self.manager)
        req.refresh_from_db()
        record_payment(
            invoice=inv_a,
            amount=Decimal("400.00"),
            approval_request=req,
            method="bank",
            reference="DET-400",
        )

        self.client.post(reverse("portal:choose_companies"), {"choice": str(self.c1.pk)})
        detail = self.client.get(reverse("portal:invoice_detail", args=[inv_a.code]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "line-A")
        self.assertContains(detail, "DET-400")
        self.assertEqual(detail.context["balance"], Decimal("600.00"))
        denied = self.client.get(reverse("portal:invoice_detail", args=[inv_b.code]))
        self.assertNotEqual(denied.status_code, 200)

        # Combined scope sees both
        self.client.post(reverse("portal:choose_companies"), {"choice": "all"})
        self.assertEqual(
            self.client.get(reverse("portal:invoice_detail", args=[inv_b.code])).status_code,
            200,
        )

    def test_official_pdf_only_when_document_attached(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.documents.models import Document, DocumentSensitivity

        inv = self._issued(self.p1, Decimal("50.00"), "pdf-line")
        self.client.post(reverse("portal:choose_companies"), {"choice": str(self.c1.pk)})
        missing = self.client.get(reverse("portal:invoice_official_download", args=[inv.code]))
        self.assertEqual(missing.status_code, 404)

        doc = Document.objects.create(
            title=f"Official {inv.code}",
            published_at=timezone.localdate(),
            company=self.c1,
            invoice=inv,
            visible_to_resident=True,
            sensitivity=DocumentSensitivity.PUBLIC_RESIDENT,
            content_type="application/pdf",
        )
        doc.file.save(
            "official.pdf",
            SimpleUploadedFile("official.pdf", b"%PDF-1.4 official", content_type="application/pdf"),
            save=True,
        )
        detail = self.client.get(reverse("portal:invoice_detail", args=[inv.code]))
        self.assertTrue(detail.context["has_official_pdf"])
        ok = self.client.get(reverse("portal:invoice_official_download", args=[inv.code]))
        self.assertEqual(ok.status_code, 200)
        self.assertIn("attachment", ok.get("Content-Disposition", ""))

        # Other company scope cannot download
        self.client.post(reverse("portal:choose_companies"), {"choice": str(self.c2.pk)})
        blocked = self.client.get(reverse("portal:invoice_official_download", args=[inv.code]))
        self.assertNotEqual(blocked.status_code, 200)


class PortalGuestPaginationDatesTests(TestCase):

    def setUp(self):
        self.company = ResidentCompany.objects.create(
            name="Guest Co", slug="guest-co", portal_active=True
        )
        self.user = User.objects.create_user(
            username="guest-u",
            email="guest-u@test.az",
            password="x",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_membership(self.user, self.company)
        self.client = Client()
        self.client.force_login(self.user)
        today = timezone.localdate()
        for i in range(55):
            guest = Guest.objects.create(first_name=f"G{i}", last_name="X")
            GuestVisit.objects.create(
                company=self.company,
                guest=guest,
                scheduled_for=today - timedelta(days=i % 10),
                status=VisitStatus.PRE_REGISTERED,
            )

    def test_pagination_preserves_from_to(self):
        today = timezone.localdate()
        start = (today - timedelta(days=29)).isoformat()
        end = today.isoformat()
        resp = self.client.get(
            reverse("portal:guests"), {"from": start, "to": end, "page": 2}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["guest_from"].isoformat(), start)
        self.assertEqual(resp.context["guest_to"].isoformat(), end)
        self.assertContains(resp, f"from={start}")
        self.assertContains(resp, f"to={end}")
        self.assertContains(resp, "page=1")


class PortalCardOrderLevelsTests(TestCase):
    def setUp(self):
        seed_ticket_taxonomy()
        self.company = ResidentCompany.objects.create(
            name="Card Co", slug="card-co", portal_active=True
        )
        self.user = User.objects.create_user(
            username="card-u",
            email="card-u@test.az",
            password="x",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_membership(self.user, self.company)

    def test_requested_level_survives_axtrax_overwrite(self):
        emp, ticket = create_employee_card_order(
            company=self.company,
            requester=self.user,
            id_document=SimpleUploadedFile("id.pdf", b"%PDF-1.4", content_type="application/pdf"),
            full_name="Kart Test",
            access_level=AccessLevel.LEVEL_2,
        )
        self.assertEqual(emp.requested_access_level, AccessLevel.LEVEL_2)
        self.assertEqual(emp.access_level, AccessLevel.LEVEL_2)
        self.assertEqual(emp.card_order_status, CardOrderStatus.SUBMITTED)
        self.assertIn("İstənilən kart səviyyəsi", ticket.description)
        # Simulate AxTrax sync writing a different actual level
        emp.access_level = AccessLevel.LEVEL_1
        emp.save(update_fields=["access_level"])
        emp.refresh_from_db()
        self.assertEqual(emp.requested_access_level, AccessLevel.LEVEL_2)
        self.assertEqual(emp.access_level, AccessLevel.LEVEL_1)


class PortalDrawingNotificationScopeTests(TestCase):
    def setUp(self):
        self.c1 = ResidentCompany.objects.create(name="Draw A", slug="draw-a", portal_active=True)
        self.c2 = ResidentCompany.objects.create(name="Draw B", slug="draw-b", portal_active=True)
        self.user = User.objects.create_user(
            username="draw-u",
            email="draw-u@test.az",
            password="x",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_memberships(self.user, [self.c1, self.c2])
        building = Building.objects.create(code="DRB", name="DRB")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        self.space = Space.objects.create(
            code="DR-1", name="DR1", floor=floor, resident=self.c1, area_m2="10"
        )
        self.drawing = create_space_drawing(
            space=self.space,
            uploaded_file=SimpleUploadedFile(
                "plan.png", b"\x89PNG\r\n", content_type="image/png"
            ),
            kind=SpaceDrawingKind.TECHNICAL_PLAN,
            uploaded_by=self.user,
            build_svg=False,
        )
        self.mgmt = User.objects.create_user(
            username="draw-mgmt",
            email="draw-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.client = Client()

    def test_drawing_result_hidden_outside_scope_and_download_enforced(self):
        req = request_drawing_access(user=self.user, drawing=self.drawing)
        decide_access_request(req=req, actor=self.mgmt, approve=True, ttl_hours=72)
        note = Notification.objects.filter(
            user=self.user, event_key=f"space_drawing_access_result:{req.pk}"
        ).first()
        self.assertIsNotNone(note)

        visible_b = user_notifications(
            self.user, namespace="portal", company_ids=[self.c2.pk], limit=None
        )
        self.assertFalse(any(n.pk == note.pk for n in visible_b))

        visible_a = user_notifications(
            self.user, namespace="portal", company_ids=[self.c1.pk], limit=None
        )
        self.assertTrue(any(n.pk == note.pk for n in visible_a))

        self.client.force_login(self.user)
        self.client.post(reverse("portal:choose_companies"), {"choice": str(self.c2.pk)})
        denied = self.client.get(reverse("portal:drawing_download", args=[self.drawing.pk]))
        self.assertNotEqual(denied.status_code, 200)
        self.assertNotIn("attachment", denied.get("Content-Disposition", ""))
