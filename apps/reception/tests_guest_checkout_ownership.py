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
from apps.comms.links import notification_target_url
from apps.reception.services import (
    ReceptionService,
    can_portal_checkout,
    checkout_guests_from_access_events,
    create_visitor_access,
    id_held_overdue_event_key,
    is_id_held_inside_overdue,
    is_portal_checkout_overdue,
    overdue_checkout_event_key,
    portal_check_out_visit,
    process_guest_overdue_alerts,
    process_id_held_inside_overdue_alerts,
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


class IdHeldInsideOverdueNotifyTests(TestCase):
    """Decision 07 — INSIDE + ID held past 24h → Reception/Security (distinct from cardless)."""

    def setUp(self):
        self.co = ResidentCompany.objects.create(name="ID Hold Co", slug="id-hold-co", portal_active=True)
        self.other = ResidentCompany.objects.create(
            name="Other Hold", slug="other-hold", portal_active=True
        )
        self.reception = User.objects.create_user(
            username="idh-rec",
            email="idh-rec@test.az",
            password="x",
            role=Role.RECEPTION,
            is_staff=True,
        )
        self.security = User.objects.create_user(
            username="idh-sec",
            email="idh-sec@test.az",
            password="x",
            role=Role.SECURITY,
            is_staff=True,
        )
        self.inactive_sec = User.objects.create_user(
            username="idh-sec-off",
            email="idh-sec-off@test.az",
            password="x",
            role=Role.SECURITY,
            is_staff=True,
            is_active=False,
        )
        self.res = User.objects.create_user(
            username="idh-res",
            email="idh-res@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=self.co,
        )
        ensure_portal_membership(self.res, self.co)
        self.client = Client()

    def _id_held_inside(self, *, company=None, check_in=None, first="Hold", last="Guest"):
        company = company or self.co
        visit = ReceptionService.register_walk_in(
            company=company,
            first_name=first,
            last_name=last,
            actor=self.reception,
            id_document_held=True,
            guest_card_number="",
            fin_code=f"AA{abs(hash(first + last)) % 10000000:07d}",
        )
        if check_in is not None:
            GuestVisit.objects.filter(pk=visit.pk).update(check_in_at=check_in)
            visit.refresh_from_db()
        return visit

    def test_boundary_just_before_exact_and_delayed_poll(self):
        now = timezone.now()
        under = self._id_held_inside(
            check_in=now - timedelta(hours=24) + timedelta(seconds=45),
            first="Under",
            last="Bound",
        )
        exact = self._id_held_inside(
            check_in=now - timedelta(hours=24),
            first="Exact",
            last="Bound",
        )
        self.assertFalse(is_id_held_inside_overdue(under, now=now))
        self.assertTrue(is_id_held_inside_overdue(exact, now=now))
        # Cardless path must ignore ID-held visits
        self.assertFalse(is_portal_checkout_overdue(exact, now=now))

        stats = process_id_held_inside_overdue_alerts(now=now)
        self.assertEqual(stats["visits"], 1)
        self.assertEqual(stats["notifications_created"], 2)  # reception + security

        rec_key = id_held_overdue_event_key(exact.pk, self.reception.pk, role_tag="rec")
        sec_key = id_held_overdue_event_key(exact.pk, self.security.pk, role_tag="sec")
        self.assertEqual(Notification.objects.filter(event_key=rec_key).count(), 1)
        self.assertEqual(Notification.objects.filter(event_key=sec_key).count(), 1)
        self.assertFalse(
            Notification.objects.filter(
                event_key=id_held_overdue_event_key(
                    exact.pk, self.inactive_sec.pk, role_tag="sec"
                )
            ).exists()
        )
        # Portal resident must not get ID-held staff alert
        self.assertFalse(
            Notification.objects.filter(user=self.res, event_key__startswith="visitor.id_held_overdue.").exists()
        )

        # Delayed / replay — no duplicates
        delayed = now + timedelta(hours=2)
        stats2 = process_guest_overdue_alerts(now=delayed)
        self.assertEqual(stats2["id_held_notifications_created"], 0)
        self.assertEqual(Notification.objects.filter(event_key=rec_key).count(), 1)

        # Scheduled command invokes combined logic
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("poll_guest_checkout_overdue", "--once", stdout=out)
        self.assertIn("id_held_visits=", out.getvalue())
        self.assertEqual(Notification.objects.filter(event_key=rec_key).count(), 1)

    def test_role_links_open_authorized_overdue_queue(self):
        now = timezone.now()
        visit = self._id_held_inside(check_in=now - timedelta(hours=25), first="Link", last="Case")
        process_id_held_inside_overdue_alerts(now=now)
        rec_note = Notification.objects.get(
            user=self.reception,
            event_key=id_held_overdue_event_key(visit.pk, self.reception.pk, role_tag="rec"),
        )
        sec_note = Notification.objects.get(
            user=self.security,
            event_key=id_held_overdue_event_key(visit.pk, self.security.pk, role_tag="sec"),
        )
        rec_url = notification_target_url(rec_note, None, self.reception, "erp")
        sec_url = notification_target_url(sec_note, None, self.security, "security")
        self.assertIn("status=inside_overdue", rec_url)
        self.assertIn("/erp/reception", rec_url)
        self.assertIn("status=inside_overdue", sec_url)
        self.assertIn("/security/", sec_url)

        self.client.force_login(self.reception)
        page = self.client.get(rec_url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, visit.guest.display_name)
        # Preview must not leak FIN / card
        self.assertNotIn("AA0001112", rec_note.message)

        self.client.force_login(self.security)
        sec_page = self.client.get(sec_url)
        self.assertEqual(sec_page.status_code, 200)
        self.assertContains(sec_page, visit.guest.display_name)

    def test_two_visits_same_person_checkout_return_and_axtrax(self):
        now = timezone.now()
        guest = Guest.objects.create(first_name="Twin", last_name="Visit", fin_code="CC3344556")
        v1 = GuestVisit.objects.create(
            guest=guest,
            company=self.co,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=now - timedelta(hours=26),
            id_document_held=True,
        )
        v2 = GuestVisit.objects.create(
            guest=guest,
            company=self.other,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=now - timedelta(hours=30),
            id_document_held=True,
        )
        stats = process_id_held_inside_overdue_alerts(now=now)
        self.assertEqual(stats["visits"], 2)
        # 2 visits × 2 active staff
        self.assertEqual(stats["notifications_created"], 4)

        # Checkout before staff resolve — reading alert does not close
        note = Notification.objects.filter(
            user=self.reception,
            event_key=id_held_overdue_event_key(v1.pk, self.reception.pk, role_tag="rec"),
        ).first()
        note.is_read = True
        note.save(update_fields=["is_read"])
        v1.refresh_from_db()
        self.assertEqual(v1.status, VisitStatus.INSIDE)
        self.assertTrue(v1.id_document_held)

        closed = ReceptionService.check_out_visit(v1, actor=self.reception, id_returned=True)
        self.assertEqual(closed.status, VisitStatus.LEFT)
        self.assertFalse(closed.id_document_held)
        # Resolved visit drops from overdue processor
        stats_after = process_id_held_inside_overdue_alerts(now=now)
        self.assertEqual(stats_after["visits"], 1)
        self.assertEqual(stats_after["notifications_created"], 0)

        # AxTrax OUT alone does not mark ID returned on remaining visit
        create_visitor_access(v2, credential="GUEST-AX-9")
        event = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=timezone.now(),
            card_number="GUEST-AX-9",
        )
        checkout_guests_from_access_events([event])
        v2.refresh_from_db()
        self.assertNotEqual(v2.status, VisitStatus.LEFT)
        self.assertTrue(v2.id_document_held)
        self.assertIsNone(v2.id_document_returned_at)

    def test_return_pending_not_labelled_inside_overdue(self):
        now = timezone.now()
        visit = self._id_held_inside(check_in=now - timedelta(hours=2), first="Pend", last="Leave")
        pending = ReceptionService.check_out_visit(
            visit, actor=self.reception, id_returned=False, allow_return_pending=True
        )
        self.assertEqual(pending.status, VisitStatus.RETURN_PENDING)
        self.assertTrue(pending.id_document_held)
        self.assertFalse(is_id_held_inside_overdue(pending, now=now + timedelta(hours=30)))
        stats = process_id_held_inside_overdue_alerts(now=now + timedelta(hours=30))
        self.assertEqual(stats["visits"], 0)
        # RETURN_PENDING uses its own event keys (not id_held_overdue)
        self.assertFalse(
            Notification.objects.filter(
                event_key__startswith=f"visitor.id_held_overdue.{pending.pk}."
            ).exists()
        )

    def test_checkout_before_cutoff_skips_alert(self):
        now = timezone.now()
        visit = self._id_held_inside(
            check_in=now - timedelta(hours=23),
            first="Early",
            last="Out",
        )
        ReceptionService.check_out_visit(visit, actor=self.reception, id_returned=True)
        later = now + timedelta(hours=5)
        self.assertEqual(process_id_held_inside_overdue_alerts(now=later)["visits"], 0)
