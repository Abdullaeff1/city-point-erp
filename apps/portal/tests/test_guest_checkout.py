from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.erp.forms import ARRIVAL_HOUR_CHOICES, PortalGuestForm
from apps.reception.models import Guest, GuestVisit, VisitStatus, VisitorAccess, VisitorAccessStatus
from apps.reception.services import can_portal_checkout, portal_check_out_visit
from apps.residents.models import ResidentCompany

User = get_user_model()


class PortalGuestFormOptionalContactTests(TestCase):
    def test_email_phone_optional(self):
        company = ResidentCompany.objects.create(name="Co", slug="co-opt", portal_active=True)
        form = PortalGuestForm(
            data={"first_name": "Ali", "last_name": "Veli"},
            company=company,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data.get("email") or "", "")
        self.assertEqual(form.cleaned_data.get("phone") or "", "")
        self.assertFalse(form.fields["email"].required)
        self.assertFalse(form.fields["phone"].required)
        self.assertNotIn("required", form.fields["email"].widget.attrs)
        self.assertNotIn("required", form.fields["phone"].widget.attrs)

    def test_expected_arrival_24h_from_nine(self):
        company = ResidentCompany.objects.create(name="Co2", slug="co-arr", portal_active=True)
        now = timezone.localtime()
        form = PortalGuestForm(company=company)
        hours = [c[0] for c in ARRIVAL_HOUR_CHOICES]
        self.assertEqual(hours[0], "09")
        self.assertEqual(hours[-1], "23")
        self.assertNotIn("08", hours)
        date_widget = form.fields["expected_arrival"].widget.widgets[0]
        self.assertEqual(date_widget.attrs["min"], now.date().isoformat())
        self.assertEqual(date_widget.attrs["max"], (now + timedelta(hours=24)).date().isoformat())

        # Pick a time >= 09:00 within the next 24h window.
        target = now + timedelta(hours=2)
        if target.hour < 9:
            target = target.replace(hour=10, minute=0, second=0, microsecond=0)
            if target <= now:
                target = now + timedelta(hours=2)
        minute = (target.minute // 5) * 5
        ok = PortalGuestForm(
            data={
                "first_name": "Ali",
                "last_name": "Veli",
                "expected_arrival_0": target.date().isoformat(),
                "expected_arrival_1": f"{target.hour:02d}",
                "expected_arrival_2": f"{minute:02d}",
            },
            company=company,
        )
        self.assertTrue(ok.is_valid(), ok.errors)
        self.assertIsNotNone(ok.cleaned_data["expected_arrival"])

        too_late = (now + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
        late = PortalGuestForm(
            data={
                "first_name": "Ali",
                "last_name": "Veli",
                "expected_arrival_0": too_late.date().isoformat(),
                "expected_arrival_1": "10",
                "expected_arrival_2": "00",
            },
            company=company,
        )
        self.assertFalse(late.is_valid())
        self.assertIn("expected_arrival", late.errors)


class PortalGuestCheckoutTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(
            name="Portal Co", slug="portal-co", portal_active=True
        )
        self.other = ResidentCompany.objects.create(
            name="Other Co", slug="other-co", portal_active=True
        )
        self.user = User.objects.create_user(
            username="res1",
            email="res1@example.com",
            password="test-pass-123",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        self.other_user = User.objects.create_user(
            username="res2",
            email="res2@example.com",
            password="test-pass-123",
            role=Role.RESIDENT_USER,
            resident_company=self.other,
        )
        self.client = Client()

    def _inside_visit(self, *, company, id_held=False, with_active_card=False):
        guest = Guest.objects.create(first_name="Qonaq", last_name="Test")
        visit = GuestVisit.objects.create(
            guest=guest,
            company=company,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=timezone.now(),
            id_document_held=id_held,
        )
        if with_active_card:
            VisitorAccess.objects.create(
                visit=visit,
                status=VisitorAccessStatus.ACTIVE,
                provider="mock",
            )
        return visit

    def test_can_checkout_without_id_or_card(self):
        visit = self._inside_visit(company=self.company)
        self.assertTrue(can_portal_checkout(visit, company=self.company))

    def test_cannot_checkout_when_id_held(self):
        visit = self._inside_visit(company=self.company, id_held=True)
        self.assertFalse(can_portal_checkout(visit, company=self.company))

    def test_cannot_checkout_when_active_card(self):
        visit = self._inside_visit(company=self.company, with_active_card=True)
        self.assertFalse(can_portal_checkout(visit, company=self.company))

    def test_portal_check_out_ok(self):
        visit = self._inside_visit(company=self.company)
        out = portal_check_out_visit(visit, actor=self.user, company=self.company)
        self.assertEqual(out.status, VisitStatus.LEFT)
        self.assertTrue(out.check_out_at)

    def test_portal_check_out_rejects_id_held(self):
        visit = self._inside_visit(company=self.company, id_held=True)
        with self.assertRaises(DomainError):
            portal_check_out_visit(visit, actor=self.user, company=self.company)

    def test_http_checkout_ok(self):
        visit = self._inside_visit(company=self.company)
        self.client.force_login(self.user)
        r = self.client.post(reverse("portal:guest_checkout", args=[visit.pk]))
        self.assertEqual(r.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.LEFT)

    def test_http_checkout_other_company_404(self):
        visit = self._inside_visit(company=self.other)
        self.client.force_login(self.user)
        r = self.client.post(reverse("portal:guest_checkout", args=[visit.pk]))
        self.assertEqual(r.status_code, 404)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.INSIDE)

    def test_http_checkout_id_held_rejected(self):
        visit = self._inside_visit(company=self.company, id_held=True)
        self.client.force_login(self.user)
        r = self.client.post(reverse("portal:guest_checkout", args=[visit.pk]))
        self.assertEqual(r.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.INSIDE)

    def test_guests_page_shows_checkout_button(self):
        visit = self._inside_visit(company=self.company)
        held = self._inside_visit(company=self.company, id_held=True)
        self.client.force_login(self.user)
        r = self.client.get(reverse("portal:guests"))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Çıxış ver", body)
        self.assertIn(f"/portal/guests/{visit.pk}/checkout/", body)
        self.assertNotIn(f"/portal/guests/{held.pk}/checkout/", body)
