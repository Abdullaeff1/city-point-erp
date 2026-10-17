from datetime import timedelta
from html import escape

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.reception.models import Guest, GuestVisit, VisitStatus, mask_fin
from apps.rbac.services import seed_rbac_catalog
from apps.residents.models import ResidentCompany

User = get_user_model()


class ResidentGuestPeriodTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(name="Ryumka MMC", slug="ryumka-mmc-ax2")
        self.other = ResidentCompany.objects.create(name="Other", slug="other-co")
        self.today = timezone.localdate()
        self.monday = self.today - timedelta(days=self.today.weekday())
        self.before_week = self.monday - timedelta(days=1)
        self.month_start = self.today.replace(day=1)
        self.outside_month = self.month_start - timedelta(days=10)

        self.inside = self._visit(
            "Inside", self.today, VisitStatus.INSIDE, check_in=True, fin_code="AA1234567"
        )
        self.portal = self._visit(
            "Portal",
            self.today,
            VisitStatus.PRE_REGISTERED,
            pre_registered=True,
        )
        self.left = self._visit("Left", self.today, VisitStatus.LEFT, check_in=True)
        self.cancelled = self._visit("Cancelled", self.today, VisitStatus.CANCELLED)
        self.before_week_visit = self._visit(
            "BeforeWeek", self.before_week, VisitStatus.WAITING
        )
        self.past = self._visit("PastMonth", self.outside_month, VisitStatus.INSIDE, check_in=True)
        if self.month_start != self.today:
            self._visit("MonthStart", self.month_start, VisitStatus.WAITING)
        self._visit(
            "OtherCo",
            self.today,
            VisitStatus.INSIDE,
            company=self.other,
            check_in=True,
        )

        self.admin = self._user("admin", Role.ADMIN)
        self.management = self._user("management", Role.MANAGEMENT)
        self.reception = self._user("reception", Role.RECEPTION)
        self.fm = self._user("fm", Role.PROPERTY_FM)
        self.desk = self._user("desk", Role.SERVICE_DESK)
        self.detail = reverse("erp:resident_detail", args=[self.company.slug])
        self.guests = reverse("erp:resident_guests", args=[self.company.slug])
        self.residents = reverse("erp:residents")
        self.employees = reverse("erp:resident_employees", args=[self.company.slug])
        self.tickets = reverse("erp:resident_tickets", args=[self.company.slug])

    def _user(self, name, role):
        return User.objects.create_user(
            username=name,
            email=f"{name}@citypoint.az",
            password="pass12345",
            role=role,
            is_staff=True,
        )

    def _visit(self, name, day, status, company=None, pre_registered=False, check_in=False, fin_code=""):
        guest = Guest.objects.create(first_name=name, last_name="Guest", fin_code=fin_code)
        return GuestVisit.objects.create(
            guest=guest,
            company=company or self.company,
            status=status,
            scheduled_for=day,
            pre_registered=pre_registered,
            check_in_at=timezone.now() if check_in else None,
        )

    def _counts(self, date_from, date_to):
        qs = GuestVisit.objects.filter(
            company=self.company,
            scheduled_for__gte=date_from,
            scheduled_for__lte=date_to,
        )
        return {
            "total": qs.count(),
            "inside": qs.filter(status=VisitStatus.INSIDE).count(),
            "waiting": qs.filter(
                status__in=[VisitStatus.WAITING, VisitStatus.PRE_REGISTERED]
            ).count(),
            "left": qs.filter(status=VisitStatus.LEFT).count(),
        }

    def test_admin_and_management_see_matching_counts(self):
        expected = self._counts(self.today, self.today)
        self.assertEqual(expected["total"], 4)
        self.assertEqual(expected["inside"], 1)
        self.assertEqual(expected["waiting"], 1)
        self.assertEqual(expected["left"], 1)
        for user in (self.admin, self.management):
            self.client.force_login(user)
            detail = self.client.get(self.detail)
            guests = self.client.get(self.guests)
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(guests.status_code, 200)
            self.assertEqual(detail.context["guest_today"], 4)
            self.assertEqual(detail.context["guest_total"], expected["total"])
            self.assertEqual(detail.context["guest_inside"], expected["inside"])
            self.assertEqual(detail.context["guest_waiting"], expected["waiting"])
            self.assertEqual(detail.context["guest_left"], expected["left"])
            self.assertEqual(guests.context["visit_total"], detail.context["guest_total"])
            self.assertEqual(guests.context["inside"], detail.context["guest_inside"])
            self.assertEqual(len(guests.context["visits"]), guests.context["visit_total"])
            self.assertContains(detail, "Bugünkü qonaq")
            self.assertContains(detail, "Resepsiya qeydləri")
            self.assertNotContains(detail, "Açıq ticket")
            self.assertContains(guests, "Portal Guest")
            self.assertNotContains(guests, "OtherCo Guest")
            self.assertNotContains(detail, "Portal Guest")
            self.assertContains(detail, reverse("erp:resident_employees", args=[self.company.slug]))
            residents = self.client.get(self.residents)
            counts = {c.slug: c.guest_today for c in residents.context["companies"]}
            self.assertEqual(counts[self.company.slug], detail.context["guest_today"])
            self.assertEqual(counts[self.other.slug], 1)

    def test_reception_sees_guests_not_employee_or_ticket_ops(self):
        seed_rbac_catalog()
        self.client.force_login(self.reception)
        detail = self.client.get(self.detail)
        guests = self.client.get(self.guests)
        residents = self.client.get(self.residents)
        self.assertEqual(detail.status_code, 200)
        self.assertFalse(detail.context["can_view_resident_ops"])
        self.assertTrue(detail.context["can_view_resident_guests"])
        self.assertEqual(detail.context["guest_today"], 4)
        self.assertEqual(guests.status_code, 200)
        self.assertEqual(guests.context["visit_total"], detail.context["guest_total"])
        self.assertContains(detail, "Resepsiya qeydləri")
        self.assertContains(guests, "AA1234567")
        self.assertNotContains(guests, mask_fin("AA1234567"))
        self.assertNotContains(detail, "Açıq ticket")
        self.assertNotContains(detail, reverse("erp:resident_employees", args=[self.company.slug]))
        counts = {c.slug: c.guest_today for c in residents.context["companies"]}
        self.assertEqual(counts[self.company.slug], 4)
        self.assertEqual(self.client.get(self.employees).status_code, 403)
        self.assertEqual(self.client.get(self.tickets).status_code, 403)

    def test_fm_and_desk_cannot_see_guest_counters(self):
        for user in (self.fm, self.desk):
            self.client.force_login(user)
            detail = self.client.get(self.detail)
            self.assertEqual(detail.status_code, 200)
            self.assertNotIn("guest_today", detail.context)
            self.assertNotIn("guest_total", detail.context)
            self.assertNotIn("guest_inside", detail.context)
            self.assertNotContains(detail, "Bugünkü qonaq")
            self.assertNotContains(detail, "Resepsiya qeydləri")
            self.assertNotContains(detail, "Dövr üzrə ziyarət")
            self.assertNotContains(detail, "Portal Guest")
            guests = self.client.get(self.guests)
            self.assertEqual(guests.status_code, 403)
            residents = self.client.get(self.residents)
            self.assertFalse(residents.context["can_view_resident_guests"])
            self.assertNotContains(residents, "Bugünkü qonaq")
            self.assertFalse(hasattr(residents.context["companies"][0], "guest_today"))

    def test_four_period_filters_and_current_status(self):
        self.client.force_login(self.admin)
        today = self.client.get(self.guests + f"?range=today&date={self.today.isoformat()}")
        self.assertEqual(today.context["visit_total"], self._counts(self.today, self.today)["total"])
        self.assertEqual(today.context["inside"], 1)
        self.assertEqual(today.context["waiting"], 1)
        self.assertContains(today, "Portal Guest")
        self.assertNotContains(today, "PastMonth Guest")
        self.assertTrue(today.context["is_today"])

        week = self.client.get(self.guests + "?range=week")
        self.assertEqual(
            week.context["visit_total"],
            self._counts(self.monday, self.today)["total"],
        )
        self.assertEqual(week.context["date_from"], self.monday)
        self.assertEqual(week.context["date_to"], self.today)
        self.assertNotContains(week, "BeforeWeek Guest")
        self.assertFalse(week.context["is_today"])
        self.assertContains(week, "cari statusudur")

        month = self.client.get(self.guests + "?range=month")
        self.assertEqual(month.context["date_from"], self.month_start)
        self.assertEqual(month.context["date_to"], self.today)
        self.assertEqual(
            month.context["visit_total"],
            self._counts(self.month_start, self.today)["total"],
        )
        self.assertNotContains(month, "PastMonth Guest")
        self.assertContains(month, "Portal Guest")

        custom = (
            f"?range=custom&from={self.outside_month.isoformat()}&to={self.outside_month.isoformat()}"
        )
        past = self.client.get(self.guests + custom)
        self.assertEqual(past.context["visit_total"], 1)
        self.assertEqual(past.context["inside"], 1)
        self.assertEqual(past.context["waiting"], 0)
        self.assertContains(past, "PastMonth Guest")
        self.assertNotContains(past, "Portal Guest")
        self.assertContains(past, "cari statusudur")

    def test_unconfirmed_portal_visit_stays_in_the_list(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.guests)
        names = [v.guest.display_name for v in response.context["visits"]]
        self.assertIn("Portal Guest", names)
        portal = next(v for v in response.context["visits"] if v.pk == self.portal.pk)
        self.assertTrue(portal.pre_registered)
        self.assertIsNone(portal.check_in_at)
        self.assertEqual(portal.status, VisitStatus.PRE_REGISTERED)

    def test_cross_page_filter_and_totals_match(self):
        self.client.force_login(self.admin)
        detail = self.client.get(self.detail + "?range=month")
        guests = self.client.get(self.guests + "?range=month")
        self.assertEqual(detail.context["guest_total"], guests.context["visit_total"])
        self.assertEqual(detail.context["guest_inside"], guests.context["inside"])
        self.assertEqual(detail.context["guest_waiting"], guests.context["waiting"])
        self.assertEqual(detail.context["guest_left"], guests.context["left"])
        self.assertEqual(detail.context["guest_today"], 4)
        self.assertContains(detail, f"{self.guests}?range=month")
        self.assertContains(guests, f"{self.detail}?range=month")

        query = (
            f"range=custom&from={self.outside_month.isoformat()}&to={self.before_week.isoformat()}"
        )
        detail_custom = self.client.get(self.detail + "?" + query)
        guests_custom = self.client.get(self.guests + "?" + query)
        self.assertEqual(detail_custom.context["guest_total"], guests_custom.context["visit_total"])
        self.assertEqual(
            detail_custom.context["guest_total"],
            self._counts(self.outside_month, self.before_week)["total"],
        )
        self.assertContains(
            detail_custom,
            escape(f"{self.guests}?{detail_custom.context['guest_query']}"),
        )
        self.assertContains(
            guests_custom,
            escape(f"{self.detail}?{guests_custom.context['guest_query']}"),
        )

    def test_legacy_date_query_still_selects_that_day(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.guests + f"?date={self.outside_month.isoformat()}")
        self.assertEqual(response.context["preset"], "today")
        self.assertEqual(response.context["visit_total"], 1)
        self.assertContains(response, "PastMonth Guest")
