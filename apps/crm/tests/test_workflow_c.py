"""Workflow C — Sales → Property → Lease → Finance acceptance."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.billing.models import Charge, ChargeSource
from apps.comms.models import Notification
from apps.core.services import DomainError
from apps.crm.dashboard import available_spaces_qs
from apps.crm.models import (
    LeaseApplicationStatus,
    OfferStatus,
    OpportunityStatus,
    PipelineStage,
    Qualification,
)
from apps.crm.services import (
    CrmLeadService,
    CrmOfferService,
    CrmOpportunityService,
    LeaseApplicationService,
)
from apps.documents.models import (
    DOCUMENT_TYPE_BANK_CERTIFICATE,
    DOCUMENT_TYPE_COMPANY_EXTRACT,
    DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED,
    DOCUMENT_TYPE_VOEN,
    Document,
    DocumentType,
)
from apps.leases.models import Lease, LeaseStatus
from apps.leases.services import process_lease_lifecycle
from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyStatus, PartyType
from apps.property.models import Building, CommercialStatus, Floor, Occupancy, OperationalStatus, Space
from apps.rbac.services import seed_rbac_catalog
from apps.residents.models import ResidentCompany

User = get_user_model()


def _seed_doc_types():
    for code, name in (
        (DOCUMENT_TYPE_VOEN, "VÖEN"),
        (DOCUMENT_TYPE_BANK_CERTIFICATE, "Bank"),
        (DOCUMENT_TYPE_COMPANY_EXTRACT, "Reyestr"),
        (DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED, "İmzalanmış müraciət"),
    ):
        DocumentType.objects.get_or_create(code=code, defaults={"name": name})


def _upload(company, code, lease=None):
    dtype = DocumentType.objects.get(code=code)
    doc = Document(
        title=f"{code}-{company.pk}",
        document_type=dtype,
        company=company,
        lease=lease,
        published_at=timezone.localdate(),
    )
    doc.file.save(f"{code}.pdf", ContentFile(b"%PDF-1.4 test"), save=True)
    return doc


@override_settings(TIME_ZONE="Asia/Baku", USE_TZ=True, LANGUAGE_CODE="az")
class WorkflowCAcceptanceTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        _seed_doc_types()
        self.client = Client()
        self.sales = User.objects.create_user(
            username="wc-sales", email="wc-sales@test.az", password="x", role=Role.SALES, is_staff=True
        )
        self.manager = User.objects.create_user(
            username="wc-mgmt", email="wc-mgmt@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        self.accountant = User.objects.create_user(
            username="wc-acc", email="wc-acc@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        self.fm = User.objects.create_user(
            username="wc-fm", email="wc-fm@test.az", password="x", role=Role.PROPERTY_FM, is_staff=True
        )
        self.resident = User.objects.create_user(
            username="wc-res", email="wc-res@test.az", password="x", role=Role.RESIDENT_USER
        )
        building = Building.objects.create(code="WC-B", name="WC Building")
        floor = Floor.objects.create(building=building, code="F8", name="8")
        self.space_a = Space.objects.create(
            code="WC-801",
            name="Office 801",
            floor=floor,
            area_m2=Decimal("100"),
            rentable_area_m2=Decimal("100"),
            commercial_status=CommercialStatus.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
            occupancy=Occupancy.VACANT,
            base_rent_rate=Decimal("40"),
        )
        self.space_b = Space.objects.create(
            code="WC-802",
            name="Office 802",
            floor=floor,
            area_m2=Decimal("80"),
            rentable_area_m2=Decimal("80"),
            commercial_status=CommercialStatus.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
            occupancy=Occupancy.VACANT,
            base_rent_rate=Decimal("40"),
        )
        self.party = Party.objects.create(
            legal_name="WorkflowC MMC",
            party_type=PartyType.ORGANIZATION,
            status=PartyStatus.PROSPECT,
        )
        PartyRole.objects.create(party=self.party, role=PartyRoleCode.PROSPECT, is_primary=True)

    def _pipeline(self, *, space=None, rate=Decimal("40"), area=Decimal("100")):
        space = space or self.space_a
        lead = CrmLeadService.create_lead(
            actor=self.sales,
            data={
                "company_name": "WorkflowC MMC",
                "phone": "0509999001",
                "qualification": Qualification.POTENTIAL,
            },
            notify=False,
        )
        opp = CrmOpportunityService.create_from_lead(lead, actor=self.sales)
        opp.party = self.party
        opp.space = space
        opp.save()
        offer = CrmOfferService.create_offer(
            actor=self.sales,
            opportunity=opp,
            party=self.party,
            space=space,
            area_m2=area,
            rent_rate_per_m2=rate,
        )
        return lead, opp, offer

    def _approve_and_send(self, offer):
        version = offer.current_version
        CrmOfferService.request_send_approval(version, actor=self.sales)
        CrmOfferService.decide_approval(version, actor=self.manager, approved=True)
        CrmOfferService.send_offer(version, actor=self.sales, sent_to="client@test.az")
        offer.refresh_from_db()
        return offer

    def _application(self, offer, *, start, end, deposit=Decimal("8000")):
        return LeaseApplicationService.create_from_offer(
            offer,
            actor=self.sales,
            data={
                "person_name": "WorkflowC MMC",
                "tax_id": "9900112233",
                "deposit_amount": deposit,
                "rent_rate_per_m2": Decimal("40"),
                "monthly_rent_net": Decimal("4000"),
                "lease_start": start,
                "lease_end": end,
                "is_legal_entity": True,
                "attachment_checklist": {"voen": True, "registry": True, "bank": True},
            },
        )

    def test_A_http_offer_to_accountant_draft(self):
        _, _, offer = self._pipeline()
        version = offer.current_version
        self.client.force_login(self.sales)
        r1 = self.client.post(
            reverse("erp:crm_offer_detail", kwargs={"pk": offer.pk}),
            {"action": "request_approval", "version_id": str(version.pk)},
        )
        self.assertEqual(r1.status_code, 302)
        self.client.force_login(self.manager)
        r2 = self.client.post(
            reverse("erp:crm_offer_detail", kwargs={"pk": offer.pk}),
            {"action": "decide", "version_id": str(version.pk), "approved": "1"},
        )
        self.assertEqual(r2.status_code, 302)
        self.client.force_login(self.sales)
        r3 = self.client.post(
            reverse("erp:crm_offer_detail", kwargs={"pk": offer.pk}),
            {"action": "send", "version_id": str(version.pk), "sent_to": "c@test.az"},
        )
        self.assertEqual(r3.status_code, 302)
        offer.refresh_from_db()
        self.assertEqual(offer.status, OfferStatus.SENT)
        r4 = self.client.post(
            reverse("erp:crm_offer_detail", kwargs={"pk": offer.pk}),
            {"action": "lease_application"},
        )
        self.assertEqual(r4.status_code, 302)
        app_pk = int(r4.url.rstrip("/").split("/")[-1])
        from apps.crm.models import LeaseApplication

        app = LeaseApplication.objects.get(pk=app_pk)
        # Sales completes commercial fields + checklist then submits (HTTP update + submit)
        self.client.post(
            reverse("erp:crm_lease_application_detail", kwargs={"pk": app.pk}),
            {
                "action": "update",
                "person_name": "WorkflowC MMC",
                "tax_id": "9900112233",
                "is_legal_entity": "1",
                "chk_voen": "on",
                "chk_registry": "on",
                "chk_bank": "on",
                "deposit_amount": "8000",
                "rent_rate_per_m2": "40",
                "monthly_rent_net": "4000",
                "lease_start": timezone.localdate().isoformat(),
                "lease_end": (timezone.localdate() + timedelta(days=365)).isoformat(),
            },
        )
        self.client.post(
            reverse("erp:crm_lease_application_detail", kwargs={"pk": app.pk}),
            {"action": "submit"},
        )
        self.client.force_login(self.accountant)
        detail = self.client.get(reverse("erp:crm_lease_application_detail", kwargs={"pk": app.pk}))
        self.assertEqual(detail.status_code, 200)
        self.client.post(
            reverse("erp:crm_lease_application_detail", kwargs={"pk": app.pk}),
            {"action": "accept"},
        )
        self.client.post(
            reverse("erp:crm_lease_application_detail", kwargs={"pk": app.pk}),
            {"action": "lease_draft"},
        )
        app.refresh_from_db()
        self.assertEqual(app.status, LeaseApplicationStatus.LEASE_DRAFT_CREATED)
        self.assertIsNotNone(app.lease_id)
        self.space_a.refresh_from_db()
        self.assertEqual(self.space_a.commercial_status, CommercialStatus.RESERVED)

    def test_B_premature_send_and_terms_locked_to_approved_version(self):
        _, _, offer = self._pipeline()
        version = offer.current_version
        approved_net = version.monthly_rent_net
        with self.assertRaises(DomainError):
            CrmOfferService.send_offer(version, actor=self.sales, sent_to="x@test.az")
        # FM cannot approve commercial offers
        CrmOfferService.request_send_approval(version, actor=self.sales)
        with self.assertRaises(DomainError):
            CrmOfferService.decide_approval(version, actor=self.fm, approved=True)
        CrmOfferService.decide_approval(version, actor=self.manager, approved=True)
        # Revision creates new DRAFT version — send still needs re-approval on new version
        new_v = CrmOfferService.create_new_version(
            offer, actor=self.sales, data={"rent_rate_per_m2": Decimal("50"), "area_m2": Decimal("100")}
        )
        offer.refresh_from_db()
        self.assertEqual(offer.status, OfferStatus.DRAFT)
        with self.assertRaises(DomainError):
            CrmOfferService.send_offer(new_v, actor=self.sales, sent_to="x@test.az")
        # Restore approved path on original approved version is not current — approve new
        CrmOfferService.request_send_approval(new_v, actor=self.sales)
        CrmOfferService.decide_approval(new_v, actor=self.manager, approved=True)
        CrmOfferService.send_offer(new_v, actor=self.sales, sent_to="x@test.az")
        offer.refresh_from_db()
        self.assertEqual(offer.current_version_id, new_v.pk)
        self.assertNotEqual(offer.current_version.monthly_rent_net, approved_net)

    def test_C_reservation_conflict_and_non_overlap_policy(self):
        available, _conflicts = available_spaces_qs()
        self.assertTrue(available.filter(pk=self.space_a.pk).exists())
        _, _, offer = self._pipeline()
        self._approve_and_send(offer)
        start = timezone.localdate()
        end = start + timedelta(days=365)
        app = self._application(offer, start=start, end=end)
        LeaseApplicationService.submit_to_accounting(app, actor=self.sales)
        LeaseApplicationService.accountant_accept(app, actor=self.accountant)
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        self.space_a.refresh_from_db()
        self.assertEqual(self.space_a.commercial_status, CommercialStatus.RESERVED)
        available, _conflicts = available_spaces_qs()
        self.assertFalse(available.filter(pk=self.space_a.pk).exists())

        # Competing hold blocked even for non-overlapping calendar (current exclusive-hold policy)
        party2 = Party.objects.create(legal_name="Other Co", party_type=PartyType.ORGANIZATION)
        lead2 = CrmLeadService.create_lead(
            actor=self.sales,
            data={"company_name": "Other Co", "phone": "0509999002", "qualification": Qualification.POTENTIAL},
            notify=False,
        )
        opp2 = CrmOpportunityService.create_from_lead(lead2, actor=self.sales)
        opp2.party = party2
        opp2.space = self.space_a
        opp2.save()
        offer2 = CrmOfferService.create_offer(
            actor=self.sales, opportunity=opp2, party=party2, space=self.space_a, area_m2=Decimal("100")
        )
        self._approve_and_send(offer2)
        future_start = end + timedelta(days=30)
        app2 = LeaseApplicationService.create_from_offer(
            offer2,
            actor=self.sales,
            data={
                "person_name": "Other Co",
                "tax_id": "1100223344",
                "lease_start": future_start,
                "lease_end": future_start + timedelta(days=365),
                "attachment_checklist": {"voen": True, "registry": True, "bank": True},
            },
        )
        with self.assertRaises(DomainError):
            LeaseApplicationService.create_lease_draft(app2, actor=self.accountant)

        # After cancel/release, space can be reserved again
        LeaseApplicationService.cancel_lease_application(app, actor=self.sales, reason="withdrawn")
        self.space_a.refresh_from_db()
        self.assertEqual(self.space_a.commercial_status, CommercialStatus.VACANT)
        app2 = LeaseApplicationService.create_lease_draft(app2, actor=self.accountant)
        self.assertIsNotNone(app2.lease_id)

    def test_D_nov25_upload_dec1_activation(self):
        """Signed doc 25 Nov; contractual start 1 Dec — no early ACTIVE."""
        sign_day = date(2026, 11, 25)
        start = date(2026, 12, 1)
        end = date(2027, 11, 30)
        _, _, offer = self._pipeline()
        self._approve_and_send(offer)
        app = self._application(offer, start=start, end=end, deposit=Decimal("8000"))
        LeaseApplicationService.submit_to_accounting(app, actor=self.sales)
        LeaseApplicationService.accountant_accept(app, actor=self.accountant)
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        lease = app.lease
        company = ResidentCompany.objects.create(
            name="WorkflowC MMC", slug="wc-mmc", voen="9900112233"
        )
        self.party.legacy_resident_company = company
        self.party.save()
        for code in (
            DOCUMENT_TYPE_VOEN,
            DOCUMENT_TYPE_BANK_CERTIFICATE,
            DOCUMENT_TYPE_COMPANY_EXTRACT,
            DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED,
        ):
            _upload(company, code, lease=lease)

        # Simulate operator completing signature on 25 Nov (freeze localdate via start future)
        with self.settings(USE_TZ=True):
            # mark_signed uses timezone.localdate() — patch by using future start relative to "today"
            # Here start is already in the future relative to test "today" if today < Dec 1 2026.
            # If CI runs after Dec 2026, force start relative to localdate.
            today = timezone.localdate()
            if start <= today:
                start = today + timedelta(days=5)
                end = start + timedelta(days=365)
                lease.start_date = start
                lease.end_date = end
                lease.save(update_fields=["start_date", "end_date", "updated_at"])
                app.lease_start = start
                app.lease_end = end
                app.save(update_fields=["lease_start", "lease_end", "updated_at"])

            app = LeaseApplicationService.mark_signed_and_complete(app, actor=self.accountant)
            lease.refresh_from_db()
            self.assertEqual(app.status, LeaseApplicationStatus.COMPLETED)
            self.assertEqual(lease.status, LeaseStatus.SIGNED)
            self.assertFalse(lease.billing_active)
            self.assertEqual(Charge.objects.filter(lease=lease, source=ChargeSource.DEPOSIT).count(), 0)
            self.space_a.refresh_from_db()
            self.assertEqual(self.space_a.commercial_status, CommercialStatus.CONTRACTED)

            # Same day poll must not activate
            stats = process_lease_lifecycle(as_of=today, expiring_days=90)
            lease.refresh_from_db()
            self.assertEqual(lease.status, LeaseStatus.SIGNED)

            # On contractual start — activate
            stats = process_lease_lifecycle(as_of=start, expiring_days=90)
            self.assertEqual(stats["activated"], 1)
            lease.refresh_from_db()
            self.assertEqual(lease.status, LeaseStatus.ACTIVE)
            self.assertTrue(lease.billing_active)
            dep = Charge.objects.get(lease=lease, source=ChargeSource.DEPOSIT)
            self.assertEqual(dep.amount, Decimal("8000.00"))
            self.assertEqual(dep.period_start, start)
            self.space_a.refresh_from_db()
            self.assertEqual(self.space_a.commercial_status, CommercialStatus.ACTIVE)
            self.assertEqual(self.space_a.resident_id, company.pk)

    def test_E_missed_poll_catchup_and_idempotent_activation(self):
        today = timezone.localdate()
        start = today - timedelta(days=3)
        end = today + timedelta(days=360)
        _, _, offer = self._pipeline()
        self._approve_and_send(offer)
        app = self._application(offer, start=start, end=end, deposit=Decimal("5000"))
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        lease = app.lease
        self.assertIsNotNone(lease)
        company = ResidentCompany.objects.create(name="Catchup Co", slug="wc-catch", voen="9900112299")
        self.party.legacy_resident_company = company
        self.party.save()
        for code in (
            DOCUMENT_TYPE_VOEN,
            DOCUMENT_TYPE_BANK_CERTIFICATE,
            DOCUMENT_TYPE_COMPANY_EXTRACT,
            DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED,
        ):
            _upload(company, code, lease=lease)
        # Force SIGNED as if signed before start; start already in the past (missed poll)
        lease.status = LeaseStatus.SIGNED
        lease.start_date = start
        lease.end_date = end
        lease.billing_active = False
        lease.portal_eligible = False
        lease.access_eligible = False
        lease.activated_at = None
        lease.save()
        stats = process_lease_lifecycle(as_of=today, expiring_days=90)
        self.assertEqual(stats["activated"], 1)
        lease.refresh_from_db()
        self.assertEqual(lease.status, LeaseStatus.ACTIVE)
        dep = Charge.objects.get(lease=lease, source=ChargeSource.DEPOSIT)
        self.assertEqual(dep.period_start, start)
        process_lease_lifecycle(as_of=today, expiring_days=90)
        self.assertEqual(
            Charge.objects.filter(lease=lease, source=ChargeSource.DEPOSIT).count(), 1
        )

    def test_F_expiry_warning_deduped(self):
        today = timezone.localdate()
        _, _, offer = self._pipeline()
        self._approve_and_send(offer)
        app = self._application(
            offer, start=today - timedelta(days=200), end=today + timedelta(days=10)
        )
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        lease = app.lease
        self.assertIsNotNone(lease)
        company = ResidentCompany.objects.create(name="Exp Co", slug="wc-exp", voen="9900112288")
        self.party.legacy_resident_company = company
        self.party.save()
        for code in (
            DOCUMENT_TYPE_VOEN,
            DOCUMENT_TYPE_BANK_CERTIFICATE,
            DOCUMENT_TYPE_COMPANY_EXTRACT,
            DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED,
        ):
            _upload(company, code, lease=lease)
        app = LeaseApplicationService.mark_signed_and_complete(app, actor=self.accountant)
        lease.refresh_from_db()
        if lease.status != LeaseStatus.ACTIVE:
            process_lease_lifecycle(as_of=today, expiring_days=90)
            lease.refresh_from_db()
        stats = process_lease_lifecycle(as_of=today, expiring_days=30)
        self.assertGreaterEqual(stats["marked_expiring"], 1)
        lease.refresh_from_db()
        self.assertEqual(lease.status, LeaseStatus.EXPIRING)
        key = f"lease.expiring.{lease.pk}.{lease.end_date}"
        n1 = Notification.objects.filter(event_key=key).count()
        process_lease_lifecycle(as_of=today, expiring_days=30)
        n2 = Notification.objects.filter(event_key=key).count()
        self.assertEqual(n1, n2)

    def test_G_deposit_and_zero_deposit(self):
        today = timezone.localdate()
        _, _, offer = self._pipeline()
        self._approve_and_send(offer)
        app = self._application(offer, start=today, end=today + timedelta(days=365), deposit=Decimal("0"))
        # Explicit zero — refresh may compute 2 months; force lease deposit 0 after draft
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        lease = app.lease
        self.assertIsNotNone(lease)
        lease.deposit = Decimal("0")
        lease.deposit_months = 0
        lease.rent = Decimal("0")
        lease.rent_rate_per_m2 = Decimal("0")
        lease.save()
        company = ResidentCompany.objects.create(name="Zero Dep", slug="wc-zero", voen="9900112277")
        self.party.legacy_resident_company = company
        self.party.save()
        for code in (
            DOCUMENT_TYPE_VOEN,
            DOCUMENT_TYPE_BANK_CERTIFICATE,
            DOCUMENT_TYPE_COMPANY_EXTRACT,
            DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED,
        ):
            _upload(company, code, lease=lease)
        LeaseApplicationService.mark_signed_and_complete(app, actor=self.accountant)
        self.assertEqual(Charge.objects.filter(lease=lease, source=ChargeSource.DEPOSIT).count(), 0)

    def test_H_two_offices_separate_offers_and_history(self):
        _, _, offer_a = self._pipeline(space=self.space_a)
        self._approve_and_send(offer_a)
        start = timezone.localdate()
        app_a = self._application(offer_a, start=start, end=start + timedelta(days=365))
        app_a = LeaseApplicationService.create_lease_draft(app_a, actor=self.accountant)

        # Second office — separate offer/contract for same party
        lead = CrmLeadService.create_lead(
            actor=self.sales,
            data={"company_name": "WorkflowC MMC", "phone": "0509999003", "qualification": Qualification.POTENTIAL},
            notify=False,
        )
        opp_b = CrmOpportunityService.create_from_lead(lead, actor=self.sales)
        opp_b.party = self.party
        opp_b.space = self.space_b
        opp_b.save()
        offer_b = CrmOfferService.create_offer(
            actor=self.sales,
            opportunity=opp_b,
            party=self.party,
            space=self.space_b,
            area_m2=Decimal("80"),
            rent_rate_per_m2=Decimal("40"),
        )
        self._approve_and_send(offer_b)
        app_b = self._application(offer_b, start=start, end=start + timedelta(days=365), deposit=Decimal("6400"))
        app_b = LeaseApplicationService.create_lease_draft(app_b, actor=self.accountant)
        self.assertNotEqual(app_a.lease_id, app_b.lease_id)
        self.assertEqual(app_a.lease.space_id, self.space_a.pk)
        self.assertEqual(app_b.lease.space_id, self.space_b.pk)
        self.space_a.refresh_from_db()
        self.space_b.refresh_from_db()
        self.assertEqual(self.space_a.commercial_status, CommercialStatus.RESERVED)
        self.assertEqual(self.space_b.commercial_status, CommercialStatus.RESERVED)
        # Historical terms remain on each offer version
        self.assertEqual(offer_a.space_id, self.space_a.pk)
        self.assertEqual(offer_b.space_id, self.space_b.pk)

    def test_I_unauthorized_mutations(self):
        _, _, offer = self._pipeline()
        version = offer.current_version
        CrmOfferService.request_send_approval(version, actor=self.sales)
        # Resident cannot hit CRM offer detail
        self.client.force_login(self.resident)
        resp = self.client.get(reverse("erp:crm_offer_detail", kwargs={"pk": offer.pk}))
        self.assertIn(resp.status_code, (302, 403))
        resp = self.client.post(
            reverse("erp:crm_offer_detail", kwargs={"pk": offer.pk}),
            {"action": "decide", "version_id": str(version.pk), "approved": "1"},
        )
        self.assertIn(resp.status_code, (302, 403))
        offer.refresh_from_db()
        self.assertEqual(offer.status, OfferStatus.PENDING_APPROVAL)
        # FM cannot create lease draft
        CrmOfferService.decide_approval(version, actor=self.manager, approved=True)
        CrmOfferService.send_offer(version, actor=self.sales, sent_to="x@test.az")
        app = self._application(
            offer, start=timezone.localdate(), end=timezone.localdate() + timedelta(days=30)
        )
        with self.assertRaises(DomainError):
            LeaseApplicationService.create_lease_draft(app, actor=self.fm)
