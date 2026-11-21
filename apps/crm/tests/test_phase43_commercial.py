"""Phase 4.3 — commercial integrity, reservation, deposit, signed docs."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.billing.models import Charge, ChargeSource
from apps.billing.services import generate_invoice_from_charges
from apps.core.services import DomainError
from apps.crm.dashboard import available_spaces_qs
from apps.crm.models import (
    LeaseApplication,
    LeaseApplicationStatus,
    OfferStatus,
    OpportunityStatus,
    PipelineStage,
    Qualification,
)
from apps.crm.services import LeaseApplicationService, CrmLeadService, CrmOfferService, CrmOpportunityService
from apps.documents.models import (
    DOCUMENT_TYPE_BANK_CERTIFICATE,
    DOCUMENT_TYPE_COMPANY_EXTRACT,
    DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED,
    DOCUMENT_TYPE_VOEN,
    Document,
    DocumentType,
)
from apps.leases.lease_ops import ensure_deposit_charge, generate_monthly_lease_charges
from apps.leases.models import Lease, LeaseAddon, LeaseStatus
from apps.leases.services import activate_lease, space_commercially_held
from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyStatus, PartyType
from apps.property.models import Building, CommercialStatus, Floor, Occupancy, OperationalStatus, Space
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


class Phase43CommercialBase(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user(
            username="s43", email="s43@test.az", password="x", role=Role.SALES, is_staff=True
        )
        self.accountant = User.objects.create_user(
            username="a43", email="a43@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        self.manager = User.objects.create_user(
            username="m43", email="m43@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        self.building = Building.objects.create(code="CP43", name="CP43")
        self.floor = Floor.objects.create(building=self.building, code="F7", name="7")
        self.space = Space.objects.create(
            code="CP43-OFF-701",
            name="701",
            floor=self.floor,
            area_m2=Decimal("100"),
            rentable_area_m2=Decimal("100"),
            commercial_status=CommercialStatus.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
            occupancy=Occupancy.VACANT,
        )
        self.party = Party.objects.create(
            legal_name="Phase43 MMC",
            party_type=PartyType.ORGANIZATION,
            status=PartyStatus.PROSPECT,
        )
        PartyRole.objects.create(party=self.party, role=PartyRoleCode.PROSPECT, is_primary=True)
        lead = CrmLeadService.create_lead(
            actor=self.sales,
            data={
                "company_name": "Phase43 MMC",
                "phone": "0500000043",
                "qualification": Qualification.POTENTIAL,
            },
            notify=False,
        )
        CrmLeadService.update_lead(
            lead, actor=self.sales, data={"qualification": Qualification.POTENTIAL}
        )
        self.opp = CrmOpportunityService.create_from_lead(lead, actor=self.sales)
        self.opp.party = self.party
        self.opp.space = self.space
        self.opp.save()
        self.offer = CrmOfferService.create_offer(
            actor=self.sales,
            opportunity=self.opp,
            party=self.party,
            space=self.space,
            area_m2=Decimal("100"),
        )
        self.offer.status = OfferStatus.SENT
        self.offer.save()
        _seed_doc_types()

    def _app(self, **extra):
        data = {
            "person_name": "Phase43 MMC",
            "tax_id": "1234567890",
            "deposit_amount": Decimal("6600.00"),
            "rent_free_note": "1 ay azadolma (sənəd)",
            "cleaning_included": False,
            "tea_service_included": False,
            "fit_out_notes": "Divar boyası lazımdır",
            "lease_start": timezone.localdate(),
            "is_legal_entity": True,
            "attachment_checklist": {"voen": True, "registry": True, "bank": True},
        }
        data.update(extra)
        return LeaseApplicationService.create_from_offer(self.offer, actor=self.sales, data=data)


class Phase43IntegrityTests(Phase43CommercialBase):
    def test_create_from_offer_idempotent(self):
        a1 = self._app()
        a2 = LeaseApplicationService.create_from_offer(self.offer, actor=self.sales)
        self.assertEqual(a1.pk, a2.pk)
        self.assertEqual(LeaseApplication.objects.filter(offer=self.offer).count(), 1)

    def test_submit_requires_attachment_checklist(self):
        app = self._app(attachment_checklist={})
        with self.assertRaises(DomainError):
            LeaseApplicationService.submit_to_accounting(app, actor=self.sales)
        app.attachment_checklist = {"voen": True, "bank": True}
        app.save(update_fields=["attachment_checklist", "updated_at"])
        with self.assertRaises(DomainError):
            LeaseApplicationService.submit_to_accounting(app, actor=self.sales)
        app.attachment_checklist = {"voen": True, "registry": True, "bank": True}
        app.save(update_fields=["attachment_checklist", "updated_at"])
        LeaseApplicationService.submit_to_accounting(app, actor=self.sales)
        app.refresh_from_db()
        self.assertEqual(app.status, LeaseApplicationStatus.SUBMITTED_TO_ACCOUNTING)

    def test_create_lease_draft_idempotent_and_reserves(self):
        app = self._app()
        LeaseApplicationService.submit_to_accounting(app, actor=self.sales)
        LeaseApplicationService.accountant_accept(app, actor=self.accountant)
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        lease_id = app.lease_id
        self.assertIsNotNone(lease_id)
        lease = app.lease
        self.assertEqual(lease.status, LeaseStatus.NEGOTIATION)
        self.space.refresh_from_db()
        self.assertEqual(self.space.commercial_status, CommercialStatus.RESERVED)
        self.assertTrue(space_commercially_held(self.space.pk))

        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        self.assertEqual(app.lease_id, lease_id)
        self.assertEqual(Lease.objects.filter(space=self.space).count(), 1)

        self.opp.refresh_from_db()
        self.assertEqual(self.opp.status, OpportunityStatus.OPEN)
        self.assertEqual(self.opp.pipeline_stage, PipelineStage.LEASE_STAGE)

        lease.refresh_from_db()
        self.assertEqual(lease.deposit, Decimal("6600.00"))
        self.assertIn("Azadolma", lease.notes)
        self.assertEqual(lease.fit_out_notes, "Divar boyası lazımdır")
        self.assertTrue(LeaseAddon.objects.filter(lease=lease, code="cleaning", is_active=False).exists())
        self.assertTrue(LeaseAddon.objects.filter(lease=lease, code="tea", is_active=False).exists())

    def test_competing_reservation_blocked(self):
        app = self._app()
        LeaseApplicationService.create_lease_draft(app, actor=self.accountant)

        party2 = Party.objects.create(legal_name="Other", party_type=PartyType.ORGANIZATION)
        opp2 = self.opp
        offer2 = CrmOfferService.create_offer(
            actor=self.sales, opportunity=opp2, party=party2, space=self.space, area_m2=Decimal("100")
        )
        offer2.status = OfferStatus.SENT
        offer2.save()
        app2 = LeaseApplicationService.create_from_offer(
            offer2, actor=self.sales, data={"person_name": "Other", "tax_id": "9999999999"}
        )
        with self.assertRaises(DomainError):
            LeaseApplicationService.create_lease_draft(app2, actor=self.accountant)

    def test_cancel_releases_reservation(self):
        app = self._app()
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        LeaseApplicationService.cancel_lease_application(app, actor=self.sales, reason="vazgecildi")
        app.refresh_from_db()
        self.assertEqual(app.status, LeaseApplicationStatus.CANCELLED)
        app.lease.refresh_from_db()
        self.assertEqual(app.lease.status, LeaseStatus.TERMINATED)
        self.space.refresh_from_db()
        self.assertEqual(self.space.commercial_status, CommercialStatus.VACANT)

    def test_reject_offer_releases(self):
        app = self._app()
        LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        LeaseApplicationService.reject_offer(self.offer, actor=self.sales, reason="qiymet")
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.status, OfferStatus.REJECTED)
        self.space.refresh_from_db()
        self.assertEqual(self.space.commercial_status, CommercialStatus.VACANT)

    def test_available_spaces_excludes_reserved(self):
        app = self._app()
        LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        available, _ = available_spaces_qs()
        self.assertFalse(available.filter(pk=self.space.pk).exists())

    def test_future_signed_syncs_contracted(self):
        app = self._app(lease_start=timezone.localdate() + timedelta(days=30))
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        company = ResidentCompany.objects.create(
            name="Phase43 MMC", slug="phase43-mmc", voen="1234567890"
        )
        self.party.legacy_resident_company = company
        self.party.save()
        _upload(company, DOCUMENT_TYPE_VOEN, lease=app.lease)
        _upload(company, DOCUMENT_TYPE_BANK_CERTIFICATE, lease=app.lease)
        _upload(company, DOCUMENT_TYPE_COMPANY_EXTRACT, lease=app.lease)
        _upload(company, DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED, lease=app.lease)
        app = LeaseApplicationService.mark_signed_and_complete(app, actor=self.accountant)
        self.assertEqual(app.status, LeaseApplicationStatus.COMPLETED)
        app.lease.refresh_from_db()
        self.assertEqual(app.lease.status, LeaseStatus.SIGNED)
        self.space.refresh_from_db()
        self.assertEqual(self.space.commercial_status, CommercialStatus.CONTRACTED)
        self.opp.refresh_from_db()
        self.assertEqual(self.opp.status, OpportunityStatus.WON)

    def test_complete_requires_signed_document(self):
        app = self._app()
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        company = ResidentCompany.objects.create(
            name="Phase43 MMC", slug="phase43-b", voen="1234567890"
        )
        self.party.legacy_resident_company = company
        self.party.save()
        _upload(company, DOCUMENT_TYPE_VOEN)
        _upload(company, DOCUMENT_TYPE_BANK_CERTIFICATE)
        _upload(company, DOCUMENT_TYPE_COMPANY_EXTRACT)
        with self.assertRaises(DomainError):
            LeaseApplicationService.mark_signed_and_complete(app, actor=self.accountant)

    def test_deposit_charge_idempotent_and_separate_invoice(self):
        app = self._app()
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        lease = app.lease
        activate_lease(lease, actor=self.accountant)
        c1 = ensure_deposit_charge(lease, actor=self.accountant)
        c2 = ensure_deposit_charge(lease, actor=self.accountant)
        self.assertEqual(c1.pk, c2.pk)
        self.assertEqual(
            Charge.objects.filter(lease=lease, source=ChargeSource.DEPOSIT).count(), 1
        )
        generate_monthly_lease_charges(as_of=timezone.localdate())
        rent = Charge.objects.filter(lease=lease, source=ChargeSource.RENT).first()
        self.assertIsNotNone(rent)
        with self.assertRaises(DomainError):
            generate_invoice_from_charges(lease.party, [c1.pk, rent.pk])
        inv = generate_invoice_from_charges(lease.party, [c1.pk])
        self.assertEqual(inv.lease_id, lease.pk)
        charge_ids = {ln.charge_id for ln in inv.lines.all() if ln.charge_id}
        self.assertEqual(charge_ids, {c1.pk})

    def test_rent_free_note_does_not_skip_rent(self):
        app = self._app()
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        activate_lease(app.lease, actor=self.accountant)
        stats = generate_monthly_lease_charges(as_of=timezone.localdate())
        self.assertGreaterEqual(stats["created"], 1)
        self.assertTrue(
            Charge.objects.filter(lease=app.lease, source=ChargeSource.RENT).exists()
        )

    def test_inactive_addon_not_charged(self):
        app = self._app()
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        activate_lease(app.lease, actor=self.accountant)
        generate_monthly_lease_charges(as_of=timezone.localdate())
        self.assertFalse(
            Charge.objects.filter(
                lease=app.lease, source=ChargeSource.ADDITIONAL, description__startswith="Təmizlik"
            ).exists()
        )

    def test_fit_out_work_order_idempotent(self):
        app = self._app()
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        wo1 = LeaseApplicationService.create_fit_out_work_order(
            app, actor=self.accountant, pay_note="İcarəçi"
        )
        wo2 = LeaseApplicationService.create_fit_out_work_order(app, actor=self.accountant)
        self.assertEqual(wo1.pk, wo2.pk)
        self.assertIn("[lease-fitout:", wo1.description)
        self.assertEqual(wo1.space_id, self.space.pk)


class Phase43ConcurrentReservationTests(TransactionTestCase):
    def setUp(self):
        self.accountant = User.objects.create_user(
            username="a43c", email="a43c@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        self.sales = User.objects.create_user(
            username="s43c", email="s43c@test.az", password="x", role=Role.SALES, is_staff=True
        )
        building = Building.objects.create(code="CP43C", name="CP43C")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        self.space = Space.objects.create(
            code="CP43C-OFF-1",
            name="1",
            floor=floor,
            area_m2=Decimal("50"),
            rentable_area_m2=Decimal("50"),
            commercial_status=CommercialStatus.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
            occupancy=Occupancy.VACANT,
        )
        self.apps = []
        for i in range(2):
            party = Party.objects.create(
                legal_name=f"Conc{i}", party_type=PartyType.ORGANIZATION
            )
            lead = CrmLeadService.create_lead(
                actor=self.sales,
                data={
                    "company_name": f"Conc{i}",
                    "phone": f"0500001{i:03d}",
                    "qualification": Qualification.POTENTIAL,
                },
                notify=False,
            )
            CrmLeadService.update_lead(
                lead, actor=self.sales, data={"qualification": Qualification.POTENTIAL}
            )
            opp = CrmOpportunityService.create_from_lead(lead, actor=self.sales)
            opp.party = party
            opp.save()
            offer = CrmOfferService.create_offer(
                actor=self.sales, opportunity=opp, party=party, space=self.space, area_m2=Decimal("50")
            )
            offer.status = OfferStatus.SENT
            offer.save()
            app = LeaseApplicationService.create_from_offer(
                offer, actor=self.sales, data={"person_name": f"Conc{i}", "tax_id": f"100000000{i}"}
            )
            self.apps.append(app)

    def test_only_one_reservation_wins(self):
        errors = []
        successes = []

        def attempt(app):
            try:
                LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
                successes.append(app.pk)
            except DomainError as exc:
                errors.append(str(exc))

        # Sequential under TransactionTestCase still validates lock+conflict;
        # true parallel threads need PostgreSQL; sequential second call must fail.
        attempt(self.apps[0])
        attempt(self.apps[1])
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(
            Lease.objects.filter(
                space=self.space, status=LeaseStatus.NEGOTIATION
            ).count(),
            1,
        )
