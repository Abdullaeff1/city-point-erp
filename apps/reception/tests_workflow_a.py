"""Workflow A — Reception↔Security guest handoff acceptance (portal, card, AxTrax OUT)."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.core.services import DomainError
from apps.integrations.axtrax_events_sync import sync_event_rows
from apps.reception.models import Guest, GuestVisit, VisitStatus, VisitorAccess, VisitorAccessStatus
from apps.reception.services import (
    ReceptionService,
    active_guest_credential_exists,
    checkout_guests_from_access_events,
    create_visitor_access,
    find_guest_access_for_event,
    normalize_guest_card,
    portal_check_out_visit,
    pre_register_visit,
)
from apps.residents.models import AccessEvent, AccessEventType, AccessResult, ResidentCompany
from apps.rbac.services import seed_rbac_catalog

User = get_user_model()


@override_settings(TIME_ZONE="Asia/Baku", USE_TZ=True)
class WorkflowAGuestAcceptanceTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.client = Client()
        self.co_a = ResidentCompany.objects.create(
            name="Alpha MMC", slug="alpha-wa", portal_active=True, status="active"
        )
        self.co_b = ResidentCompany.objects.create(
            name="Beta MMC", slug="beta-wa", portal_active=True, status="active"
        )
        self.reception = User.objects.create_user(
            username="wa-rec",
            email="wa-rec@test.az",
            password="x",
            role=Role.RECEPTION,
            is_staff=True,
        )
        self.security = User.objects.create_user(
            username="wa-sec",
            email="wa-sec@test.az",
            password="x",
            role=Role.SECURITY,
            is_staff=True,
        )
        self.res_a = User.objects.create_user(
            username="wa-resa",
            email="wa-resa@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=self.co_a,
        )
        ensure_portal_membership(self.res_a, self.co_a)
        self.res_b = User.objects.create_user(
            username="wa-resb",
            email="wa-resb@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=self.co_b,
        )
        ensure_portal_membership(self.res_b, self.co_b)
        self.res_multi = User.objects.create_user(
            username="wa-multi",
            email="wa-multi@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=self.co_a,
        )
        ensure_portal_membership(self.res_multi, self.co_a)
        ensure_portal_membership(self.res_multi, self.co_b)

    def test_A_prereg_optional_contacts_then_reception_admit(self):
        visit = pre_register_visit(
            company=self.co_a,
            first_name="Leyla",
            last_name="Qonaq",
            email="",
            phone="",
            portal_user=self.res_a,
        )
        self.assertEqual(visit.status, VisitStatus.PRE_REGISTERED)
        self.assertEqual(visit.company_id, self.co_a.pk)
        admitted = ReceptionService.check_in_visit(
            visit,
            actor=self.reception,
            id_document_held=False,
            id_override_reason="Portal qonaq",
            allow_id_override=True,
        )
        self.assertEqual(admitted.status, VisitStatus.INSIDE)
        self.assertIsNotNone(admitted.check_in_at)
        self.client.force_login(self.reception)
        journal = self.client.get(reverse("erp:reception"), {"range": "today"})
        self.assertEqual(journal.status_code, 200)
        self.assertContains(journal, "Leyla")
        self.assertContains(journal, "Alpha MMC")

    def test_B_walk_in_without_card_or_custody(self):
        visit = ReceptionService.register_walk_in(
            company=self.co_a,
            fin_code="",
            first_name="Nicat",
            last_name="WalkIn",
            actor=self.reception,
            id_document_held=False,
            guest_card_number="",
            id_override_reason="Qısa görüş",
            allow_id_override=True,
        )
        self.assertEqual(visit.status, VisitStatus.INSIDE)
        self.assertFalse(visit.id_document_held)
        self.assertFalse(VisitorAccess.objects.filter(visit=visit).exists())
        self.client.force_login(self.security)
        sec = self.client.get(
            reverse("security:guests"), {"range": "today", "company": str(self.co_a.pk)}
        )
        self.assertEqual(sec.status_code, 200)
        self.assertContains(sec, "Nicat")

    def test_C_resident_cardless_checkout(self):
        guest = Guest.objects.create(first_name="Cardless", last_name="Out")
        visit = GuestVisit.objects.create(
            guest=guest,
            company=self.co_a,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=timezone.now() - timedelta(hours=1),
            id_document_held=False,
        )
        closed = portal_check_out_visit(visit, actor=self.res_a, company=self.co_a)
        self.assertEqual(closed.status, VisitStatus.LEFT)
        self.assertIsNotNone(closed.check_out_at)
        stamp = closed.check_out_at
        with self.assertRaises(DomainError):
            portal_check_out_visit(closed, actor=self.res_a, company=self.co_a)
        closed.refresh_from_db()
        self.assertEqual(closed.check_out_at, stamp)

    def test_D_other_company_and_multi_membership(self):
        guest = Guest.objects.create(first_name="Scope", last_name="Guest")
        visit = GuestVisit.objects.create(
            guest=guest,
            company=self.co_a,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=timezone.now(),
            id_document_held=False,
        )
        with self.assertRaises(DomainError):
            portal_check_out_visit(visit, actor=self.res_b, company=self.co_b)
        # Multi-company user acting for own company A
        closed = portal_check_out_visit(visit, actor=self.res_multi, company=self.co_a)
        self.assertEqual(closed.status, VisitStatus.LEFT)
        self.client.force_login(self.res_b)
        resp = self.client.post(
            reverse("portal:guest_checkout", kwargs={"pk": visit.pk}),
            {},
        )
        self.assertIn(resp.status_code, (302, 403, 404))

    def test_E_resident_blocked_for_card_or_closed(self):
        guest = Guest.objects.create(first_name="Card", last_name="Hold")
        visit = GuestVisit.objects.create(
            guest=guest,
            company=self.co_a,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=timezone.now(),
            id_document_held=False,
        )
        create_visitor_access(visit, credential="007001")
        with self.assertRaises(DomainError):
            portal_check_out_visit(visit, actor=self.res_a, company=self.co_a)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.INSIDE)
        self.assertIsNone(visit.check_out_at)

    def test_card_normalize_preserves_leading_zeros(self):
        self.assertEqual(normalize_guest_card("007001"), "007001")
        self.assertTrue(active_guest_credential_exists("007001") is False)
        guest = Guest.objects.create(first_name="Z", last_name="Card")
        visit = GuestVisit.objects.create(
            guest=guest,
            company=self.co_a,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=timezone.now(),
        )
        access = create_visitor_access(visit, credential="007001")
        self.assertEqual(access.credential, "007001")
        self.assertTrue(active_guest_credential_exists("007001"))
        self.assertTrue(active_guest_credential_exists("7001"))

    def test_auto_checkout_uses_event_time_and_dedupes(self):
        guest = Guest.objects.create(first_name="Auto", last_name="Exit")
        check_in = timezone.now() - timedelta(hours=2)
        visit = GuestVisit.objects.create(
            guest=guest,
            company=self.co_a,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=check_in,
            id_document_held=False,
        )
        create_visitor_access(visit, credential="GK-900")
        departed = check_in + timedelta(hours=1)
        event = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=departed,
            card_number="GK-900",
        )
        n = checkout_guests_from_access_events([event])
        self.assertEqual(n, 1)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.LEFT)
        self.assertEqual(visit.check_out_at, departed)
        # Reprocess same event — no change
        n2 = checkout_guests_from_access_events([event, event])
        self.assertEqual(n2, 0)
        visit.refresh_from_db()
        self.assertEqual(visit.check_out_at, departed)

    def test_entry_or_wrong_card_does_not_close(self):
        guest = Guest.objects.create(first_name="Stay", last_name="Inside")
        visit = GuestVisit.objects.create(
            guest=guest,
            company=self.co_a,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=timezone.now() - timedelta(minutes=30),
        )
        create_visitor_access(visit, credential="GK-IN")
        entry = AccessEvent.objects.create(
            event_type=AccessEventType.IN,
            result=AccessResult.GRANTED,
            occurred_at=timezone.now(),
            card_number="GK-IN",
        )
        other = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=timezone.now(),
            card_number="OTHER",
        )
        self.assertEqual(checkout_guests_from_access_events([entry, other]), 0)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.INSIDE)

    def test_card_reuse_delayed_exit_does_not_close_next_guest(self):
        g1 = Guest.objects.create(first_name="A", last_name="First")
        g2 = Guest.objects.create(first_name="B", last_name="Second")
        t0 = timezone.now() - timedelta(hours=5)
        t1 = t0 + timedelta(hours=1)
        t2 = t0 + timedelta(hours=2)
        t3 = t0 + timedelta(hours=3)
        visit_a = GuestVisit.objects.create(
            guest=g1,
            company=self.co_a,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=t0,
        )
        create_visitor_access(visit_a, credential="SHARED-1")
        # Close A via turnstile at t1
        ev_a = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=t1,
            card_number="SHARED-1",
        )
        self.assertEqual(checkout_guests_from_access_events([ev_a]), 1)
        visit_a.refresh_from_db()
        self.assertEqual(visit_a.status, VisitStatus.LEFT)
        access_a = visit_a.visitor_access
        self.assertEqual(access_a.status, VisitorAccessStatus.REVOKED)
        self.assertIsNotNone(access_a.valid_until)

        # Issue same physical card to B at t2
        visit_b = GuestVisit.objects.create(
            guest=g2,
            company=self.co_a,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=t2,
        )
        create_visitor_access(visit_b, credential="SHARED-1")
        # Delayed/replayed exit belonging to A's interval
        late_a = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=t1 + timedelta(minutes=5),
            card_number="SHARED-1",
        )
        self.assertEqual(checkout_guests_from_access_events([late_a]), 0)
        visit_b.refresh_from_db()
        self.assertEqual(visit_b.status, VisitStatus.INSIDE)
        # Genuine B exit at t3
        ev_b = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=t3,
            card_number="SHARED-1",
        )
        self.assertEqual(checkout_guests_from_access_events([ev_b]), 1)
        visit_b.refresh_from_db()
        self.assertEqual(visit_b.status, VisitStatus.LEFT)
        self.assertEqual(visit_b.check_out_at, t3)

    def test_ambiguity_preserves_open_visit(self):
        # Two ACTIVE assignments with overlapping intervals for same card → no auto close.
        g1 = Guest.objects.create(first_name="X1", last_name="Amb")
        g2 = Guest.objects.create(first_name="X2", last_name="Amb")
        now = timezone.now()
        v1 = GuestVisit.objects.create(
            guest=g1, company=self.co_a, status=VisitStatus.INSIDE, scheduled_for=timezone.localdate(), check_in_at=now
        )
        v2 = GuestVisit.objects.create(
            guest=g2, company=self.co_a, status=VisitStatus.INSIDE, scheduled_for=timezone.localdate(), check_in_at=now
        )
        a1 = create_visitor_access(v1, credential="AMB-9")
        a2 = create_visitor_access(v2, credential="AMB-9")
        self.assertIsNone(find_guest_access_for_event(card="AMB-9", occurred_at=now + timedelta(minutes=1)))
        ev = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=now + timedelta(minutes=1),
            card_number="AMB-9",
        )
        self.assertEqual(checkout_guests_from_access_events([ev]), 0)
        v1.refresh_from_db()
        v2.refresh_from_db()
        self.assertEqual(v1.status, VisitStatus.INSIDE)
        self.assertEqual(v2.status, VisitStatus.INSIDE)
        self.assertEqual(a1.credential, a2.credential)
        from apps.integrations.models import SyncLog
        from apps.reception.services import GUEST_CHECKOUT_AMBIGUOUS_OP

        self.assertTrue(
            SyncLog.objects.filter(
                operation=GUEST_CHECKOUT_AMBIGUOUS_OP,
                correlation_id=f"access_event:{ev.pk}",
            ).exists()
        )

    def test_reception_close_precedes_later_axtrax_exit(self):
        guest = Guest.objects.create(first_name="Man", last_name="Close")
        visit = GuestVisit.objects.create(
            guest=guest,
            company=self.co_a,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=timezone.now() - timedelta(hours=1),
            id_document_held=False,
        )
        create_visitor_access(visit, credential="MAN-1")
        closed = ReceptionService.check_out_visit(visit, actor=self.reception, id_returned=True)
        stamp = closed.check_out_at
        later = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=timezone.now(),
            card_number="MAN-1",
        )
        self.assertEqual(checkout_guests_from_access_events([later]), 0)
        closed.refresh_from_db()
        self.assertEqual(closed.status, VisitStatus.LEFT)
        self.assertEqual(closed.check_out_at, stamp)

    def test_return_pending_shows_exit_known_id_held(self):
        guest = Guest.objects.create(first_name="ID", last_name="Held")
        visit = GuestVisit.objects.create(
            guest=guest,
            company=self.co_a,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=timezone.now() - timedelta(hours=1),
            id_document_held=True,
        )
        create_visitor_access(visit, credential="ID-1")
        departed = timezone.now() - timedelta(minutes=10)
        ev = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=departed,
            card_number="ID-1",
        )
        self.assertEqual(checkout_guests_from_access_events([ev]), 1)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.RETURN_PENDING)
        self.assertEqual(visit.check_out_at, departed)
        self.assertTrue(visit.id_document_held)
        self.client.force_login(self.reception)
        page = self.client.get(reverse("erp:reception"), {"status": "id_pending"})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Çıxış · vəsiqə gözləyir")

    def test_overnight_journal_by_scheduled_for(self):
        """Journal date filter uses scheduled_for (Asia/Baku local date)."""
        guest = Guest.objects.create(first_name="Night", last_name="Owl")
        yesterday = timezone.localdate() - timedelta(days=1)
        # Check-in late yesterday, checkout after midnight today
        check_in = timezone.make_aware(datetime.combine(yesterday, datetime.strptime("23:30", "%H:%M").time()))
        check_out = check_in + timedelta(hours=2)
        visit = GuestVisit.objects.create(
            guest=guest,
            company=self.co_a,
            status=VisitStatus.LEFT,
            scheduled_for=yesterday,
            check_in_at=check_in,
            check_out_at=check_out,
            id_document_held=False,
        )
        self.client.force_login(self.security)
        day_page = self.client.get(
            reverse("security:guests"),
            {"range": "custom", "from": yesterday.isoformat(), "to": yesterday.isoformat()},
        )
        self.assertEqual(day_page.status_code, 200)
        self.assertContains(day_page, "Night")
        today_page = self.client.get(
            reverse("security:guests"),
            {"range": "today", "date": timezone.localdate().isoformat()},
        )
        self.assertEqual(today_page.status_code, 200)
        # Visit belongs to yesterday's scheduled_for — not listed on today-only journal
        names = [v.guest.display_name for v in today_page.context["visits"]]
        self.assertNotIn("Night Owl", names)
        visit.refresh_from_db()
        self.assertEqual(visit.check_out_at, check_out)

    def test_axtrax_sync_unavailability_then_resume(self):
        """Reception admit works without sync; later synthetic OUT closes once."""
        visit = ReceptionService.register_walk_in(
            company=self.co_a,
            first_name="Sync",
            last_name="Later",
            actor=self.reception,
            id_document_held=True,
            guest_card_number="SYNC-44",
            fin_code="AA1234567",
        )
        self.assertEqual(visit.status, VisitStatus.INSIDE)
        # Simulate sync resume with synthetic row processor path via AccessEvent + checkout
        departed = timezone.now()
        event = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=departed,
            card_number="SYNC-44",
        )
        self.assertEqual(checkout_guests_from_access_events([event]), 1)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.RETURN_PENDING)
        self.assertEqual(checkout_guests_from_access_events([event]), 0)
