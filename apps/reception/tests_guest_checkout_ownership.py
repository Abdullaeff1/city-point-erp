"""City Point — guest checkout ownership, 24h portal alerts, AxTrax evidence-only."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.comms.models import Notification
from apps.core.services import DomainError
from apps.reception.models import Guest, GuestVisit, VisitStatus, VisitorAccessStatus
from apps.reception.services import (
    ReceptionService,
    can_portal_checkout,
    checkout_guests_from_access_events,
    create_visitor_access,
    is_portal_checkout_overdue,
    overdue_checkout_event_key,
    portal_check_out_visit,
    process_portal_checkout_overdue_alerts,
)
from apps.residents.models import AccessEvent, AccessEventType, AccessResult, ResidentCompany

User = get_user_model()


class GuestCheckoutOwnershipTests(TestCase):
    def setUp(self):
        self.co = ResidentCompany.objects.create(name="Own Co", slug="own-co", portal_active=True)
        self.other = ResidentCompany.objects.create(
            name="Other Co", slug="other-own", portal_active=True
        )
        self.reception = User.objects.create_user(
            username="own-rec",
            email="own-rec@test.az",
            password="x",
            role=Role.RECEPTION,
            is_staff=True,
        )
        self.res = User.objects.create_user(
            username="own-res",
            email="own-res@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=self.co,
        )
        ensure_portal_membership(self.res, self.co)
        self.res_other = User.objects.create_user(
            username="own-res2",
            email="own-res2@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=self.other,
        )
        ensure_portal_membership(self.res_other, self.other)
        self.client = Client()

    def _cardless_inside(self, *, company=None, check_in=None):
        company = company or self.co
        guest = Guest.objects.create(first_name="Cardless", last_name="Guest")
        return GuestVisit.objects.create(
            guest=guest,
            company=company,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=check_in or timezone.now(),
            id_document_held=False,
        )

    def test_reception_checkout_returned_guest_card(self):
        visit = ReceptionService.register_walk_in(
            company=self.co,
            first_name="Kart",
            last_name="Qaytar",
            actor=self.reception,
            id_document_held=True,
            guest_card_number="QONAQ-77",
            fin_code="AA1122334",
        )
        self.assertTrue(visit.id_document_held)
        closed = ReceptionService.check_out_visit(
            visit, actor=self.reception, id_returned=True
        )
        self.assertEqual(closed.status, VisitStatus.LEFT)
        self.assertFalse(closed.id_document_held)
        self.assertIsNotNone(closed.id_document_returned_at)
        self.assertIsNotNone(closed.check_out_recorded_at)
        self.assertIsNone(closed.actual_departure_at)

    def test_resident_checkout_reception_walk_in_cardless(self):
        visit = ReceptionService.register_walk_in(
            company=self.co,
            fin_code="",
            first_name="Walk",
            last_name="In",
            actor=self.reception,
            id_document_held=False,
            guest_card_number="",
            allow_id_override=True,
            id_override_reason="qısa",
        )
        self.assertTrue(can_portal_checkout(visit, company=self.co))
        out = portal_check_out_visit(visit, actor=self.res, company=self.co)
        self.assertEqual(out.status, VisitStatus.LEFT)
        self.assertEqual(out.check_out_recorded_at, out.check_out_at)
        self.assertIsNone(out.actual_departure_at)
        # Repeated submission safe
        again = portal_check_out_visit(out, actor=self.res, company=self.co)
        self.assertEqual(again.pk, out.pk)
        self.assertEqual(again.status, VisitStatus.LEFT)

    def test_deny_other_company_and_card_issued(self):
        visit = self._cardless_inside()
        with self.assertRaises(DomainError):
            portal_check_out_visit(visit, actor=self.res_other, company=self.other)
        carded = self._cardless_inside()
        create_visitor_access(carded, credential="CARD-9")
        self.assertFalse(can_portal_checkout(carded, company=self.co))
        with self.assertRaises(DomainError):
            portal_check_out_visit(carded, actor=self.res, company=self.co)

    def test_exact_24h_boundary_and_scheduler_idempotent(self):
        now = timezone.now()
        under = self._cardless_inside(check_in=now - timedelta(hours=24) + timedelta(seconds=30))
        over = self._cardless_inside(check_in=now - timedelta(hours=24) - timedelta(seconds=1))
        self.assertFalse(is_portal_checkout_overdue(under, now=now))
        self.assertTrue(is_portal_checkout_overdue(over, now=now))

        stats1 = process_portal_checkout_overdue_alerts(now=now)
        self.assertGreaterEqual(stats1["notifications_created"], 1)
        key = overdue_checkout_event_key(over.pk, self.res.pk)
        self.assertEqual(Notification.objects.filter(user=self.res, event_key=key).count(), 1)
        # Repeat scheduler — no duplicate
        stats2 = process_portal_checkout_overdue_alerts(now=now)
        self.assertEqual(stats2["notifications_created"], 0)
        self.assertEqual(Notification.objects.filter(user=self.res, event_key=key).count(), 1)

    def test_checkout_after_alert_read_clears_outstanding(self):
        now = timezone.now()
        visit = self._cardless_inside(check_in=now - timedelta(hours=25))
        process_portal_checkout_overdue_alerts(now=now)
        note = Notification.objects.get(
            user=self.res, event_key=overdue_checkout_event_key(visit.pk, self.res.pk)
        )
        note.is_read = True
        note.save(update_fields=["is_read"])
        # Reading alert leaves visit open
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.INSIDE)
        self.client.force_login(self.res)
        page = self.client.get(reverse("portal:guests"), {"overdue": "1", "days": "90"})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "24s+ çıxış gecikir")
        portal_check_out_visit(visit, actor=self.res, company=self.co)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.LEFT)
        page2 = self.client.get(reverse("portal:guests"), {"overdue": "1", "days": "90"})
        self.assertNotContains(page2, visit.guest.display_name)

    def test_axtrax_out_does_not_finalize_card_return(self):
        visit = ReceptionService.register_walk_in(
            company=self.co,
            first_name="Ax",
            last_name="Hold",
            actor=self.reception,
            id_document_held=True,
            guest_card_number="AX-CARD-1",
            fin_code="BB9988776",
        )
        event = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=timezone.now(),
            card_number="AX-CARD-1",
        )
        self.assertEqual(checkout_guests_from_access_events([event]), 0)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.INSIDE)
        self.assertTrue(visit.id_document_held)
        self.assertIsNone(visit.id_document_returned_at)
        # Access event remains as passage evidence
        self.assertTrue(AccessEvent.objects.filter(pk=event.pk).exists())

    def test_known_departure_validated_and_distinct_from_recorded(self):
        visit = self._cardless_inside(check_in=timezone.now() - timedelta(hours=3))
        known = timezone.now() - timedelta(hours=1)
        out = portal_check_out_visit(
            visit, actor=self.res, company=self.co, departed_at=known
        )
        self.assertEqual(out.actual_departure_at, known)
        self.assertIsNotNone(out.check_out_recorded_at)
        self.assertGreaterEqual(out.check_out_recorded_at, known)
        with self.assertRaises(DomainError):
            visit2 = self._cardless_inside(check_in=timezone.now() - timedelta(hours=1))
            portal_check_out_visit(
                visit2,
                actor=self.res,
                company=self.co,
                departed_at=timezone.now() + timedelta(minutes=5),
            )

    def test_portal_and_reception_ui_show_checkout_time_or_dash(self):
        """UI shows check_out_at simply; open visits show —."""
        recorded = timezone.now() - timedelta(minutes=12)
        visit = GuestVisit.objects.create(
            guest=Guest.objects.create(first_name="Late", last_name="UI"),
            company=self.co,
            status=VisitStatus.LEFT,
            scheduled_for=timezone.localdate(),
            check_in_at=timezone.now() - timedelta(hours=30),
            check_out_at=recorded,
            check_out_recorded_at=recorded,
            actual_departure_at=None,
        )
        open_visit = GuestVisit.objects.create(
            guest=Guest.objects.create(first_name="Open", last_name="UI"),
            company=self.co,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=timezone.now() - timedelta(hours=1),
        )
        recorded_disp = timezone.localtime(recorded).strftime("%H:%M")
        guest_label = visit.guest.display_name

        self.client.force_login(self.res)
        portal = self.client.get(reverse("portal:guests"), {"days": "90"})
        self.assertEqual(portal.status_code, 200)
        portal_body = portal.content.decode()
        self.assertIn(guest_label, portal_body)
        self.assertNotIn("Qeyd:", portal_body)
        row_start = portal_body.find(guest_label)
        portal_row = portal_body[row_start : row_start + 1200]
        self.assertNotIn("Naməlum", portal_row)

        self.client.force_login(self.reception)
        journal = self.client.get(
            reverse("erp:reception"),
            {"status": "left", "from": timezone.localdate().isoformat()},
        )
        self.assertEqual(journal.status_code, 200)
        journal_body = journal.content.decode()
        j_start = journal_body.find(guest_label)
        self.assertGreaterEqual(j_start, 0)
        journal_row = journal_body[j_start : j_start + 800]
        self.assertIn(recorded_disp, journal_row)
        self.assertNotIn("Naməlum", journal_row)
        self.assertNotIn("Qeyd:", journal_row)

        inside = self.client.get(
            reverse("erp:reception"),
            {"status": "inside", "from": timezone.localdate().isoformat()},
        )
        self.assertEqual(inside.status_code, 200)
        inside_body = inside.content.decode()
        i_start = inside_body.find(open_visit.guest.display_name)
        self.assertGreaterEqual(i_start, 0)
        inside_row = inside_body[i_start : i_start + 800]
        self.assertIn("—", inside_row)

    def test_alert_recipients_are_active_company_memberships(self):
        from apps.accounts.models import PortalCompanyMembership
        from apps.reception.services import portal_guest_alert_recipients

        inactive = User.objects.create_user(
            username="own-inactive",
            email="own-inactive@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=self.co,
            is_active=True,
        )
        PortalCompanyMembership.objects.create(
            user=inactive, company=self.co, is_active=False
        )
        recipients = list(portal_guest_alert_recipients(self.co))
        self.assertIn(self.res, recipients)
        self.assertNotIn(inactive, recipients)
        self.assertNotIn(self.res_other, recipients)
