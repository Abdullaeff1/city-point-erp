"""Deferred in-app notifications: check-in, lease activation, offer reject, RETURN_PENDING."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.comms.links import notification_target_url
from apps.comms.models import Notification
from apps.core import events as bus
from apps.core.event_handlers import register_default_handlers
from apps.core.services import DomainError
from apps.crm.models import (
    Offer,
    OfferStatus,
    Opportunity,
    OpportunityStatus,
    PipelineStage,
)
from apps.crm.services import CrmOfferService, LeaseApplicationService
from apps.leases.models import Lease, LeaseStatus
from apps.leases.services import activate_lease, process_lease_lifecycle
from apps.parties.models import Party, PartyStatus, PartyType
from apps.property.models import (
    Building,
    CommercialStatus,
    Floor,
    Occupancy,
    OperationalStatus,
    Space,
)
from apps.rbac.services import seed_rbac_catalog
from apps.reception.models import VisitStatus, VisitorType
from apps.reception.services import ReceptionService, pre_register_visit
from apps.residents.models import ResidentCompany

User = get_user_model()


class DeferredNotifyBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def setUp(self):
        bus.clear_handlers()
        register_default_handlers()
        self.client = Client()
        self.company = ResidentCompany.objects.create(
            name="Notify Co", slug="notify-co", portal_active=True
        )
        self.other_co = ResidentCompany.objects.create(
            name="Other Co", slug="other-co-n", portal_active=True
        )
        self.portal = User.objects.create_user(
            username="portal-n",
            email="portal-n@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        ensure_portal_membership(self.portal, self.company)
        self.other_portal = User.objects.create_user(
            username="portal-o",
            email="portal-o@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.other_co,
        )
        ensure_portal_membership(self.other_portal, self.other_co)
        self.reception = User.objects.create_user(
            username="rec-n",
            email="rec-n@test.az",
            password="Pass12345!",
            role=Role.RECEPTION,
            is_staff=True,
        )
        self.security = User.objects.create_user(
            username="sec-n",
            email="sec-n@test.az",
            password="Pass12345!",
            role=Role.SECURITY,
            is_staff=True,
        )
        self.sales = User.objects.create_user(
            username="sales-n",
            email="sales-n@test.az",
            password="Pass12345!",
            role=Role.SALES,
            is_staff=True,
        )
        self.accountant = User.objects.create_user(
            username="acc-n",
            email="acc-n@test.az",
            password="Pass12345!",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.mgmt = User.objects.create_user(
            username="mgmt-n",
            email="mgmt-n@test.az",
            password="Pass12345!",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.courier, _ = VisitorType.objects.get_or_create(
            code="courier", defaults={"name": "Kuryer", "sort_order": 10}
        )


class GuestCheckInNotifyTests(DeferredNotifyBase):
    def test_pre_register_alone_does_not_notify(self):
        visit = pre_register_visit(
            company=self.company,
            first_name="Ali",
            last_name="Qonaq",
            portal_user=self.portal,
            visit_type=self.courier,
        )
        self.assertEqual(visit.status, VisitStatus.PRE_REGISTERED)
        self.assertFalse(
            Notification.objects.filter(
                user=self.portal, event_key=f"visitor.checked_in.{visit.pk}"
            ).exists()
        )

    def test_check_in_notifies_portal_creator_once_and_opens_guests(self):
        visit = pre_register_visit(
            company=self.company,
            first_name="Ali",
            last_name="Qonaq",
            portal_user=self.portal,
            visit_type=self.courier,
        )
        ReceptionService.check_in_visit(visit, actor=self.reception, id_document_held=False)
        key = f"visitor.checked_in.{visit.pk}"
        notes = list(Notification.objects.filter(user=self.portal, event_key=key))
        self.assertEqual(len(notes), 1)
        self.assertIn("Ali", notes[0].message)
        self.assertNotIn("FIN", notes[0].message.upper())
        # Replay emit — still one arrival notice.
        bus.emit(
            bus.VISITOR_CHECKED_IN,
            payload={"visit_id": visit.pk, "company_id": self.company.pk, "entity_model": "visit"},
            event_key=f"visitor.checked_in.{visit.pk}",
        )
        self.assertEqual(Notification.objects.filter(user=self.portal, event_key=key).count(), 1)
        # Other company cannot see this notice.
        self.assertFalse(Notification.objects.filter(user=self.other_portal).exists())
        # Recipient screen + destination.
        self.client.force_login(self.portal)
        page = self.client.get(reverse("portal:alerts"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Qonağınız qəbul edildi")
        guests = reverse("portal:guests")
        self.assertContains(page, f'href="{guests}"')
        dest = self.client.get(guests)
        self.assertEqual(dest.status_code, 200)
        self.assertContains(dest, "Ali")

    def test_two_visits_remain_distinguishable(self):
        v1 = pre_register_visit(
            company=self.company,
            first_name="Bir",
            last_name="A",
            portal_user=self.portal,
            visit_type=self.courier,
        )
        v2 = pre_register_visit(
            company=self.company,
            first_name="Iki",
            last_name="B",
            portal_user=self.portal,
            visit_type=self.courier,
        )
        for v in (v1, v2):
            ReceptionService.check_in_visit(v, actor=self.reception, id_document_held=False)
            ReceptionService.check_out_visit(v, actor=self.reception, id_returned=True)
        self.assertEqual(
            Notification.objects.filter(
                user=self.portal, event_key=f"visitor.checked_in.{v1.pk}"
            ).count(),
            1,
        )
        self.assertEqual(
            Notification.objects.filter(
                user=self.portal, event_key=f"visitor.checked_in.{v2.pk}"
            ).count(),
            1,
        )

    def test_walk_in_without_portal_creator_does_not_fan_out(self):
        before = Notification.objects.count()
        ReceptionService.register_walk_in(
            fin_code="",
            first_name="Walk",
            last_name="In",
            company=self.company,
            visit_type=self.courier,
            id_document_held=False,
            actor=self.reception,
        )
        # No Security/Reception/company-wide arrival fan-out without CP policy.
        self.assertEqual(Notification.objects.count(), before)

    def test_inactive_portal_creator_skipped(self):
        visit = pre_register_visit(
            company=self.company,
            first_name="X",
            last_name="Y",
            portal_user=self.portal,
            visit_type=self.courier,
        )
        self.portal.is_active = False
        self.portal.save(update_fields=["is_active"])
        ReceptionService.check_in_visit(visit, actor=self.reception, id_document_held=False)
        self.assertFalse(
            Notification.objects.filter(event_key=f"visitor.checked_in.{visit.pk}").exists()
        )


class LeaseActivationNotifyTests(DeferredNotifyBase):
    def _space_party(self):
        building = Building.objects.create(code="NLA", name="NLA")
        floor = Floor.objects.create(building=building, code="1", name="1")
        space = Space.objects.create(
            floor=floor,
            code="NLA-101",
            name="101",
            area_m2=Decimal("40"),
            rentable_area_m2=Decimal("40"),
            occupancy=Occupancy.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
            commercial_status=CommercialStatus.VACANT,
            base_rent_rate=Decimal("10"),
        )
        party = Party.objects.create(
            legal_name="Notify Tenant",
            party_type=PartyType.ORGANIZATION,
            status=PartyStatus.ACTIVE,
            legacy_resident_company=self.company,
        )
        return space, party

    def test_immediate_and_idempotent_activation_notify_once(self):
        space, party = self._space_party()
        lease = Lease.objects.create(
            code="LS-N-1",
            party=party,
            space=space,
            status=LeaseStatus.SIGNED,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=365),
            rent=Decimal("1000"),
            deposit=Decimal("2000"),
        )
        activate_lease(lease, actor=self.accountant)
        key_prefix = f"lease.activated.{lease.pk}."
        for user in (self.sales, self.accountant, self.mgmt):
            self.assertEqual(
                Notification.objects.filter(
                    user=user, event_key=f"{key_prefix}{user.pk}"
                ).count(),
                1,
            )
        # Second call on ACTIVE is idempotent — no second emit/notify.
        activate_lease(lease, actor=self.accountant)
        self.assertEqual(
            Notification.objects.filter(event_key__startswith=key_prefix).count(),
            Notification.objects.filter(event_key__startswith=key_prefix).distinct().count(),
        )
        count_after = Notification.objects.filter(
            user=self.sales, event_key=f"{key_prefix}{self.sales.pk}"
        ).count()
        self.assertEqual(count_after, 1)

    def test_scheduled_activation_preserves_start_date_and_notifies(self):
        space, party = self._space_party()
        start = timezone.localdate() - timedelta(days=2)
        lease = Lease.objects.create(
            code="LS-N-2",
            party=party,
            space=space,
            status=LeaseStatus.SIGNED,
            start_date=start,
            end_date=start + timedelta(days=365),
            rent=Decimal("800"),
            deposit=Decimal("1600"),
        )
        result = process_lease_lifecycle(as_of=timezone.localdate())
        self.assertGreaterEqual(result["activated"], 1)
        lease.refresh_from_db()
        self.assertEqual(lease.status, LeaseStatus.ACTIVE)
        self.assertEqual(lease.start_date, start)
        self.assertTrue(
            Notification.objects.filter(
                user=self.accountant, event_key=f"lease.activated.{lease.pk}.{self.accountant.pk}"
            ).exists()
        )
        # Retry lifecycle after downtime — no duplicate activation notify.
        process_lease_lifecycle(as_of=timezone.localdate())
        self.assertEqual(
            Notification.objects.filter(
                user=self.accountant, event_key=f"lease.activated.{lease.pk}.{self.accountant.pk}"
            ).count(),
            1,
        )

    def test_recipient_opens_lease_detail(self):
        space, party = self._space_party()
        lease = Lease.objects.create(
            code="LS-N-3",
            party=party,
            space=space,
            status=LeaseStatus.SIGNED,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=100),
            rent=Decimal("500"),
            deposit=Decimal("1000"),
        )
        activate_lease(lease, actor=self.sales)
        note = Notification.objects.get(
            user=self.sales, event_key=f"lease.activated.{lease.pk}.{self.sales.pk}"
        )
        url = notification_target_url(note, None, self.sales, "erp")
        self.assertEqual(url, reverse("erp:lease_detail", kwargs={"code": lease.code}))
        self.client.force_login(self.sales)
        page = self.client.get(reverse("erp:alerts"))
        self.assertContains(page, "İcarə aktivləşdi")
        self.assertContains(page, f'href="{url}"')
        detail = self.client.get(url)
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, lease.code)


class OfferRejectNotifyTests(DeferredNotifyBase):
    def _party_opp(self, *, owner):
        party = Party.objects.create(
            legal_name="Offer Party",
            party_type=PartyType.ORGANIZATION,
            status=PartyStatus.ACTIVE,
        )
        opp = Opportunity.objects.create(
            title="Opp",
            owner=owner,
            created_by=owner,
            party=party,
            status=OpportunityStatus.OPEN,
            pipeline_stage=PipelineStage.NEGOTIATION,
        )
        return party, opp

    def test_management_reject_reuses_approval_decided(self):
        party, opp = self._party_opp(owner=self.sales)
        offer = CrmOfferService.create_offer(
            actor=self.sales,
            opportunity=opp,
            party=party,
            area_m2=Decimal("100"),
        )
        version = offer.current_version
        CrmOfferService.request_send_approval(version, actor=self.sales)
        version.refresh_from_db()
        CrmOfferService.decide_approval(
            version, actor=self.mgmt, approved=False, comment="internal"
        )
        notes = Notification.objects.filter(
            user=self.sales,
            event_key__startswith=f"approval.decided.{version.approval_request_id}.",
        )
        self.assertEqual(notes.count(), 1)
        self.assertIn("rədd", notes[0].message.lower())
        self.assertNotIn("internal", notes[0].message)
        url = notification_target_url(notes[0], None, self.sales, "erp")
        self.assertEqual(url, reverse("erp:crm_offer_detail", kwargs={"pk": offer.pk}))
        # Later submitted version can produce its own decision notice.
        version2 = CrmOfferService.create_new_version(
            offer,
            actor=self.sales,
            data={"rent_rate_per_m2": Decimal("45"), "area_m2": Decimal("100")},
        )
        CrmOfferService.request_send_approval(version2, actor=self.sales)
        version2.refresh_from_db()
        CrmOfferService.decide_approval(version2, actor=self.mgmt, approved=True)
        self.assertEqual(
            Notification.objects.filter(
                user=self.sales, event_key__startswith="approval.decided."
            ).count(),
            2,
        )

    def test_customer_reject_notifies_owner_without_reason_leak(self):
        party, opp = self._party_opp(owner=self.sales)
        offer = Offer.objects.create(
            opportunity=opp,
            party=party,
            status=OfferStatus.SENT,
            rent_amount=Decimal("1000"),
        )
        LeaseApplicationService.reject_offer(
            offer, actor=self.sales, reason="budget secret"
        )
        note = Notification.objects.get(
            user=self.sales, event_key=f"crm.offer.rejected.{offer.pk}"
        )
        self.assertNotIn("budget secret", note.message)
        self.client.force_login(self.sales)
        page = self.client.get(reverse("erp:alerts"))
        self.assertContains(page, "Ticarət təklifi rədd edildi")
        detail_url = reverse("erp:crm_offer_detail", kwargs={"pk": offer.pk})
        self.assertContains(page, f'href="{detail_url}"')
        self.sales.role = Role.RECEPTION
        self.sales.save(update_fields=["role"])
        url = notification_target_url(note, None, self.sales, "erp")
        self.assertEqual(url, "")


class ReturnPendingCapTests(DeferredNotifyBase):
    def test_all_eligible_recipients_above_20(self):
        """Characterization of complete delivery (no [:20] cap).

        Policy audience = every active Security + Reception (phase6 UAT A2).
        Ordering = pk ascending. Not a duty-roster priority.
        """
        extras_sec = [
            User.objects.create_user(
                username=f"sec-x{i}",
                email=f"sec-x{i}@test.az",
                password="Pass12345!",
                role=Role.SECURITY,
                is_staff=True,
            )
            for i in range(20)
        ]
        extras_rec = [
            User.objects.create_user(
                username=f"rec-x{i}",
                email=f"rec-x{i}@test.az",
                password="Pass12345!",
                role=Role.RECEPTION,
                is_staff=True,
            )
            for i in range(20)
        ]
        sec_count = User.objects.filter(role=Role.SECURITY, is_active=True).count()
        rec_count = User.objects.filter(role=Role.RECEPTION, is_active=True).count()
        self.assertGreaterEqual(sec_count, 21)
        self.assertGreaterEqual(rec_count, 21)

        visit = ReceptionService.register_walk_in(
            fin_code="ABC1234",
            first_name="Cap",
            last_name="Test",
            company=self.company,
            visit_type=self.courier,
            id_document_held=True,
            actor=self.reception,
        )
        ReceptionService.check_out_visit(
            visit, actor=self.reception, id_returned=False, allow_return_pending=True
        )
        sec_notes = Notification.objects.filter(
            event_key__startswith=f"visitor.return_pending.{visit.pk}.sec."
        )
        rec_notes = Notification.objects.filter(
            event_key__startswith=f"visitor.return_pending.{visit.pk}.rec."
        )
        self.assertEqual(sec_notes.count(), sec_count)
        self.assertEqual(rec_notes.count(), rec_count)
        # Display name only — no FIN in messages.
        sample = sec_notes.first().message
        self.assertNotIn("ABC1234", sample)
        # Recipient screen for Security lands on guests journal.
        self.client.force_login(self.security)
        page = self.client.get(reverse("security:alerts"))
        self.assertContains(page, "vəsiqə gözləyir")
        self.assertContains(page, reverse("security:guests"))

    def test_rolled_back_check_in_no_success_notify(self):
        visit = pre_register_visit(
            company=self.company,
            first_name="Roll",
            last_name="Back",
            portal_user=self.portal,
            visit_type=self.courier,
        )
        ReceptionService.check_in_visit(visit, actor=self.reception, id_document_held=False)
        key = f"visitor.checked_in.{visit.pk}"
        self.assertEqual(Notification.objects.filter(event_key=key).count(), 1)
        twin = pre_register_visit(
            company=self.company,
            first_name="Roll",
            last_name="Back",
            portal_user=self.portal,
            visit_type=self.courier,
        )
        twin.guest = visit.guest
        twin.save(update_fields=["guest"])
        before = Notification.objects.count()
        with self.assertRaises(DomainError):
            ReceptionService.check_in_visit(
                twin, actor=self.reception, id_document_held=False
            )
        self.assertEqual(Notification.objects.count(), before)
        self.assertFalse(
            Notification.objects.filter(event_key=f"visitor.checked_in.{twin.pk}").exists()
        )
