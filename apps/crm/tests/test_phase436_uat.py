"""Phase 4.3.6 — E2E UAT, concurrency, document ACL, financial integrity, FM PR scope."""

from __future__ import annotations

import threading
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.billing.models import Charge, ChargeSource
from apps.billing.services import confirm_invoice, generate_invoice_from_charges, record_payment
from apps.core.services import DomainError
from apps.crm.models import (
    ActivityType,
    LeaseApplicationStatus,
    OfferStatus,
    OpportunityStatus,
    PipelineStage,
    Qualification,
    RecordStatus,
)
from apps.crm.services import (
    CrmLeadService,
    CrmOfferService,
    CrmOpportunityService,
    LeaseApplicationService,
)
from apps.documents.access import clamp_portal_visibility, sensitivity_for_new_document
from apps.documents.models import (
    DOCUMENT_TYPE_BANK_CERTIFICATE,
    DOCUMENT_TYPE_COMPANY_EXTRACT,
    DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED,
    DOCUMENT_TYPE_OTHER,
    DOCUMENT_TYPE_VOEN,
    Document,
    DocumentSensitivity,
    DocumentType,
)
from apps.documents.services import DocumentService
from apps.leases.lease_ops import ensure_deposit_charge, generate_monthly_lease_charges
from apps.leases.models import Lease, LeaseAddon, LeaseStatus
from apps.leases.services import activate_lease
from apps.parties.models import Party, PartyType
from apps.procurement.models import PRSource, PRStatus, PurchaseApprovalLimit, PurchaseRequest
from apps.procurement.services import ProcurementService
from apps.property.models import Building, CommercialStatus, Floor, Occupancy, OperationalStatus, Space
from apps.rbac.services import seed_rbac_catalog
from apps.residents.models import ResidentCompany
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


def _seed_doc_types():
    for code, name in (
        (DOCUMENT_TYPE_VOEN, "VÖEN"),
        (DOCUMENT_TYPE_BANK_CERTIFICATE, "Bank"),
        (DOCUMENT_TYPE_COMPANY_EXTRACT, "Reyestr"),
        (DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED, "İmzalanmış müraciət"),
        (DOCUMENT_TYPE_OTHER, "Digər"),
    ):
        DocumentType.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "default_sensitivity": (
                    DocumentSensitivity.CONFIDENTIAL
                    if code != DOCUMENT_TYPE_OTHER
                    else DocumentSensitivity.INTERNAL
                ),
            },
        )


def _upload(company, code, lease=None):
    dtype = DocumentType.objects.get(code=code)
    doc = Document(
        title=f"{code}-{company.pk}",
        document_type=dtype,
        company=company,
        lease=lease,
        published_at=timezone.localdate(),
        sensitivity=DocumentSensitivity.CONFIDENTIAL,
        visible_to_resident=False,
    )
    doc.file.save(f"{code}.pdf", ContentFile(b"%PDF-1.4 test"), save=True)
    return doc


class Phase436CommercialE2ETests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.sales = User.objects.create_user(
            username="s436", email="s436@test.az", password="x", role=Role.SALES, is_staff=True
        )
        self.accountant = User.objects.create_user(
            username="a436", email="a436@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        self.manager = User.objects.create_user(
            username="m436", email="m436@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        building = Building.objects.create(code="CP436", name="CP436")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        self.space = Space.objects.create(
            code="CP436-OFF-1",
            name="1",
            floor=floor,
            area_m2=Decimal("100"),
            rentable_area_m2=Decimal("100"),
            commercial_status=CommercialStatus.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
            occupancy=Occupancy.VACANT,
        )
        self.party = Party.objects.create(legal_name="UAT MMC", party_type=PartyType.ORGANIZATION)
        _seed_doc_types()

    def test_lead_to_payment_e2e(self):
        lead = CrmLeadService.create_lead(
            actor=self.sales,
            data={
                "company_name": "UAT MMC",
                "phone": "0501111436",
                "qualification": Qualification.POTENTIAL,
                "initial_note": "Qiymət: 33 AZN; sahə CP436-OFF-1",
            },
            notify=False,
        )
        CrmLeadService.update_lead(
            lead,
            actor=self.sales,
            data={"qualification": Qualification.POTENTIAL, "pipeline_stage": PipelineStage.WORKING},
        )
        CrmLeadService.add_activity(
            lead,
            actor=self.sales,
            activity_type=ActivityType.VIEWING,
            body="Sayt ziyarəti",
        )
        self.assertEqual(lead.record_status, RecordStatus.OPEN)
        self.assertNotEqual(lead.pipeline_stage, PipelineStage.WON)

        opp = CrmOpportunityService.create_from_lead(lead, actor=self.sales)
        opp.party = self.party
        opp.space = self.space
        opp.save()
        offer = CrmOfferService.create_offer(
            actor=self.sales,
            opportunity=opp,
            party=self.party,
            space=self.space,
            area_m2=Decimal("100"),
            rent_rate_per_m2=Decimal("33"),
        )
        version = offer.current_version
        CrmOfferService.request_send_approval(version, actor=self.sales)
        CrmOfferService.decide_approval(version, actor=self.manager, approved=True)
        CrmOfferService.send_offer(version, actor=self.sales, sent_to="uat@test.az")
        offer.refresh_from_db()
        self.assertEqual(offer.status, OfferStatus.SENT)

        app = LeaseApplicationService.create_from_offer(
            offer,
            actor=self.sales,
            data={
                "person_name": "UAT MMC",
                "tax_id": "4360000001",
                "legal_address": "Bakı hüquqi",
                "actual_address": "Bakı faktiki",
                "use_purpose": "Ofis",
                "rent_rate_per_m2": Decimal("33"),
                "monthly_rent_net": Decimal("3300"),
                "deposit_amount": Decimal("6600"),
                "rent_free_note": "1 ay azadolma (sənəd)",
                "cleaning_included": False,
                "tea_service_included": True,
                "fit_out_notes": "Boyama",
                "extra_notes": "Əlavə",
                "signer_title_name": "Direktor — Ali",
                "lease_start": timezone.localdate(),
                "lease_end": timezone.localdate() + timedelta(days=365),
                "is_legal_entity": True,
                "attachment_checklist": {"voen": True, "registry": True, "bank": True},
                "bank_requisites": {"bank_name": "Kapital", "voen": "4360000001"},
            },
        )
        LeaseApplicationService.submit_to_accounting(app, actor=self.sales)
        LeaseApplicationService.accountant_accept(app, actor=self.accountant)
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        lease = app.lease
        self.assertEqual(lease.status, LeaseStatus.NEGOTIATION)
        self.space.refresh_from_db()
        self.assertEqual(self.space.commercial_status, CommercialStatus.RESERVED)
        self.assertIn("Azadolma", lease.notes)
        self.assertEqual(lease.fit_out_notes, "Boyama")
        self.assertEqual(lease.deposit, Decimal("6600.00"))
        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.OPEN)
        self.assertNotEqual(opp.pipeline_stage, PipelineStage.WON)

        company = ResidentCompany.objects.create(
            name="UAT MMC", slug="uat-mmc-436", voen="4360000001", legal_address="Köhnə"
        )
        self.party.legacy_resident_company = company
        self.party.save()
        _upload(company, DOCUMENT_TYPE_VOEN, lease=lease)
        _upload(company, DOCUMENT_TYPE_BANK_CERTIFICATE, lease=lease)
        _upload(company, DOCUMENT_TYPE_COMPANY_EXTRACT, lease=lease)
        _upload(company, DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED, lease=lease)

        app = LeaseApplicationService.mark_signed_and_complete(app, actor=self.accountant)
        self.assertEqual(app.status, LeaseApplicationStatus.COMPLETED)
        lease.refresh_from_db()
        self.assertEqual(lease.status, LeaseStatus.ACTIVE)
        self.space.refresh_from_db()
        self.assertEqual(self.space.commercial_status, CommercialStatus.ACTIVE)
        self.assertEqual(self.space.resident_id, company.pk)
        company.refresh_from_db()
        # copy-if-empty: existing legal_address preserved
        self.assertEqual(company.legal_address, "Köhnə")
        opp.refresh_from_db()
        self.assertEqual(opp.status, OpportunityStatus.WON)

        dep = Charge.objects.get(lease=lease, source=ChargeSource.DEPOSIT)
        self.assertEqual(dep.amount, Decimal("6600.00"))
        activate_lease(lease, actor=self.accountant)
        self.assertEqual(
            Charge.objects.filter(lease=lease, source=ChargeSource.DEPOSIT).count(), 1
        )

        generate_monthly_lease_charges(as_of=timezone.localdate())
        rent = Charge.objects.filter(lease=lease, source=ChargeSource.RENT).first()
        self.assertIsNotNone(rent)
        with self.assertRaises(DomainError):
            generate_invoice_from_charges(self.party, [dep.pk, rent.pk])
        from apps.billing.models import InvoiceStatus

        inv = generate_invoice_from_charges(self.party, [dep.pk])
        self.assertEqual(inv.lease_id, lease.pk)
        confirm_invoice(inv)
        req = ApprovalService.request(
            workflow_code="finance.payment",
            requested_by=self.accountant,
            entity=inv,
            payload={
                "invoice_id": inv.pk,
                "invoice_code": inv.code,
                "amount": str(inv.total),
                "method": "bank",
                "reference": "UAT-DEP",
            },
        )
        ApprovalService.decide(req, approved=True, decided_by=self.manager, comment="ok")
        req.refresh_from_db()
        record_payment(
            invoice=inv,
            amount=inv.total,
            method="bank",
            reference="UAT-DEP",
            approval_request=req,
        )
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.PAID)

    def test_deposit_defaults_to_two_months_when_blank(self):
        space = Space.objects.create(
            code="CP436-OFF-DEF",
            name="def",
            floor=self.space.floor,
            area_m2=Decimal("100"),
            rentable_area_m2=Decimal("100"),
            commercial_status=CommercialStatus.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
            occupancy=Occupancy.VACANT,
        )
        party = Party.objects.create(legal_name="DefDep", party_type=PartyType.ORGANIZATION)
        lead = CrmLeadService.create_lead(
            actor=self.sales,
            data={"company_name": "DefDep", "phone": "0502222436", "qualification": Qualification.POTENTIAL},
            notify=False,
        )
        CrmLeadService.update_lead(
            lead, actor=self.sales, data={"qualification": Qualification.POTENTIAL}
        )
        opp = CrmOpportunityService.create_from_lead(lead, actor=self.sales)
        opp.party = party
        opp.save()
        offer = CrmOfferService.create_offer(
            actor=self.sales,
            opportunity=opp,
            party=party,
            space=space,
            area_m2=Decimal("100"),
            rent_rate_per_m2=Decimal("40"),
        )
        offer.status = OfferStatus.SENT
        offer.save()
        app = LeaseApplicationService.create_from_offer(
            offer,
            actor=self.sales,
            data={
                "person_name": "DefDep",
                "tax_id": "4360000002",
                "rent_rate_per_m2": Decimal("40"),
                "monthly_rent_net": Decimal("4000"),
                "lease_start": timezone.localdate(),
                "attachment_checklist": {"voen": True, "registry": True, "bank": True},
            },
        )
        app = LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        self.assertEqual(app.lease.deposit_months, 2)
        self.assertEqual(app.lease.deposit, Decimal("8000.00"))

    def test_zero_deposit_skips_charge(self):
        space = Space.objects.create(
            code="CP436-OFF-ZERO",
            name="zero",
            floor=self.space.floor,
            area_m2=Decimal("10"),
            rentable_area_m2=Decimal("10"),
            commercial_status=CommercialStatus.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
            occupancy=Occupancy.VACANT,
        )
        party = Party.objects.create(legal_name="ZeroDep", party_type=PartyType.ORGANIZATION)
        lease = Lease.objects.create(
            code="L-ZERO-DEP",
            party=party,
            space=space,
            status=LeaseStatus.SIGNED,
            rent=Decimal("0"),
            deposit=Decimal("0"),
            deposit_months=0,
            start_date=timezone.localdate(),
        )
        activate_lease(lease, actor=self.accountant)
        self.assertFalse(
            Charge.objects.filter(lease=lease, source=ChargeSource.DEPOSIT).exists()
        )


class Phase436DocumentSecurityTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        _seed_doc_types()
        self.company = ResidentCompany.objects.create(name="DocCo", slug="docco-436", voen="4369")
        self.other = ResidentCompany.objects.create(name="OtherCo", slug="otherco-436", voen="4368")
        self.admin = User.objects.create_user(
            username="doc-admin", email="da@test.az", password="x", role=Role.ADMIN, is_staff=True
        )
        self.resident = User.objects.create_user(
            username="doc-res",
            email="dr@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        ensure_portal_membership(self.resident, self.company)

    def test_signed_application_cannot_be_forced_portal_public(self):
        dtype = DocumentType.objects.get(code=DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED)
        self.assertFalse(
            clamp_portal_visibility(document_type=dtype, visible_to_resident=True)
        )
        self.assertEqual(
            sensitivity_for_new_document(document_type=dtype, visible_to_resident=True),
            DocumentSensitivity.CONFIDENTIAL,
        )
        uploaded = ContentFile(b"%PDF-1.4 x", name="signed.pdf")
        doc = DocumentService.upload_new(
            title="Signed",
            uploaded_file=uploaded,
            company=self.company,
            document_type=dtype,
            created_by=self.admin,
            visible_to_resident=True,
        )
        self.assertFalse(doc.visible_to_resident)
        self.assertEqual(doc.sensitivity, DocumentSensitivity.CONFIDENTIAL)

        DocumentService.update_meta(
            doc, visible_to_resident=True, actor=self.admin
        )
        doc.refresh_from_db()
        self.assertFalse(doc.visible_to_resident)
        self.assertNotEqual(doc.sensitivity, DocumentSensitivity.PUBLIC_RESIDENT)

    def test_portal_download_denies_confidential_even_if_visible_flag_set(self):
        dtype = DocumentType.objects.get(code=DOCUMENT_TYPE_LEASE_APPLICATION_SIGNED)
        doc = Document.objects.create(
            title="Leak attempt",
            document_type=dtype,
            company=self.company,
            published_at=timezone.localdate(),
            sensitivity=DocumentSensitivity.CONFIDENTIAL,
            visible_to_resident=True,
        )
        doc.file.save("leak.pdf", ContentFile(b"%PDF-1.4"), save=True)
        client = Client()
        client.force_login(self.resident)
        client.post(reverse("portal:choose_companies"), {"choice": str(self.company.pk)})
        resp = client.get(reverse("portal:document_download", kwargs={"pk": doc.pk}))
        self.assertIn(resp.status_code, {302, 403})

    def test_other_types_can_still_be_portal_public(self):
        dtype = DocumentType.objects.get(code=DOCUMENT_TYPE_OTHER)
        self.assertTrue(clamp_portal_visibility(document_type=dtype, visible_to_resident=True))
        self.assertEqual(
            sensitivity_for_new_document(document_type=dtype, visible_to_resident=True),
            DocumentSensitivity.PUBLIC_RESIDENT,
        )


class Phase436ProcurementScopeTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.fm = User.objects.create_user(
            username="fm436", email="fm436@test.az", password="x", role=Role.PROPERTY_FM, is_staff=True
        )
        self.admin = User.objects.create_user(
            username="adm436", email="adm436@test.az", password="x", role=Role.ADMIN, is_staff=True, is_superuser=True
        )
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.PROPERTY_FM, defaults={"max_amount": Decimal("100"), "is_active": True}
        )
        from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
        from apps.maintenance.services import next_wo_code

        self.wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title="FM scope WO",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )

    def test_fm_cannot_approve_manual_pr(self):
        pr = PurchaseRequest.objects.create(
            code="PR-MAN-436",
            title="Manual",
            status=PRStatus.SUBMITTED,
            requested_by=self.fm,
            source=PRSource.MANUAL,
        )
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)

    def test_fm_unpriced_wo_pr_escalates_for_management(self):
        """PR has no unit price — FM cannot locally approve by treating qty as AZN."""
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="bolt", qty="2"
        )
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)
        pr.refresh_from_db()
        self.assertEqual(pr.status, PRStatus.SUBMITTED)
        self.assertTrue(
            ApprovalRequest.objects.filter(
                workflow_code="procurement.pr",
                status=ApprovalStatus.PENDING,
                entity_id=pr.pk,
            ).exists()
        )

    def test_admin_can_approve_manual_pr(self):
        from apps.procurement.models import PRLine

        pr = PurchaseRequest.objects.create(
            code="PR-MAN-ADM",
            title="Manual admin",
            status=PRStatus.SUBMITTED,
            requested_by=self.admin,
            source=PRSource.MANUAL,
        )
        PRLine.objects.create(pr=pr, description="admin line", qty=Decimal("1"), unit="pcs")
        ProcurementService.approve_pr(pr, actor=self.admin)
        pr.refresh_from_db()
        self.assertEqual(pr.status, PRStatus.APPROVED)


class Phase436TrueConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.accountant = User.objects.create_user(
            username="a436c", email="a436c@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        self.sales = User.objects.create_user(
            username="s436c", email="s436c@test.az", password="x", role=Role.SALES, is_staff=True
        )
        building = Building.objects.create(code="CP436C", name="CP436C")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        self.space = Space.objects.create(
            code="CP436C-OFF-1",
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
            party = Party.objects.create(legal_name=f"ParC{i}", party_type=PartyType.ORGANIZATION)
            lead = CrmLeadService.create_lead(
                actor=self.sales,
                data={
                    "company_name": f"ParC{i}",
                    "phone": f"0504361{i:03d}",
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
                offer,
                actor=self.sales,
                data={
                    "person_name": f"ParC{i}",
                    "tax_id": f"436100000{i}",
                    "attachment_checklist": {"voen": True, "registry": True, "bank": True},
                },
            )
            self.apps.append(app)

    def test_parallel_reservation_only_one_wins(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL row-level locks")

        barrier = threading.Barrier(2, timeout=15)
        successes: list[int] = []
        errors: list[str] = []
        lock = threading.Lock()
        accountant_id = self.accountant.pk
        app_ids = [self.apps[0].pk, self.apps[1].pk]

        def attempt(app_id: int):
            connections.close_all()
            try:
                actor = User.objects.get(pk=accountant_id)
                from apps.crm.models import LeaseApplication

                app = LeaseApplication.objects.get(pk=app_id)
                barrier.wait()
                LeaseApplicationService.create_lease_draft(app, actor=actor)
                with lock:
                    successes.append(app_id)
            except DomainError as exc:
                with lock:
                    errors.append(str(exc))
            except Exception as exc:  # noqa: BLE001 — capture unexpected for assertion
                with lock:
                    errors.append(f"{type(exc).__name__}:{exc}")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=attempt, args=(aid,)) for aid in app_ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)
            self.assertFalse(t.is_alive(), "worker hung — possible deadlock")

        self.assertEqual(len(successes), 1, successes)
        self.assertEqual(len(errors), 1, errors)
        self.assertEqual(
            Lease.objects.filter(space_id=self.space.pk, status=LeaseStatus.NEGOTIATION).count(),
            1,
        )
        self.space.refresh_from_db()
        self.assertEqual(self.space.commercial_status, CommercialStatus.RESERVED)

    def test_parallel_activate_single_deposit(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL row-level locks")

        party = Party.objects.create(legal_name="DepRace", party_type=PartyType.ORGANIZATION)
        lease = Lease.objects.create(
            code="L-DEP-RACE",
            party=party,
            space=self.space,
            status=LeaseStatus.SIGNED,
            rent=Decimal("1000"),
            deposit=Decimal("2000"),
            deposit_months=2,
            start_date=timezone.localdate(),
        )
        barrier = threading.Barrier(2, timeout=15)
        results: list[str] = []
        lock = threading.Lock()
        lease_id = lease.pk
        actor_id = self.accountant.pk

        def run():
            connections.close_all()
            try:
                actor = User.objects.get(pk=actor_id)
                barrier.wait()
                activate_lease(Lease.objects.get(pk=lease_id), actor=actor)
                with lock:
                    results.append("ok")
            except Exception as exc:  # noqa: BLE001
                with lock:
                    results.append(f"err:{type(exc).__name__}:{exc}")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=run) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)
            self.assertFalse(t.is_alive())

        self.assertEqual(results.count("ok"), 2, results)
        self.assertEqual(
            Charge.objects.filter(lease_id=lease_id, source=ChargeSource.DEPOSIT).count(),
            1,
        )


class Phase436AddonBillingTests(TestCase):
    def setUp(self):
        self.accountant = User.objects.create_user(
            username="addon-acc", email="addon@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        building = Building.objects.create(code="CP436A", name="CP436A")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        self.space = Space.objects.create(
            code="CP436A-OFF-1",
            name="1",
            floor=floor,
            area_m2=Decimal("100"),
            rentable_area_m2=Decimal("100"),
            commercial_status=CommercialStatus.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
            occupancy=Occupancy.VACANT,
        )
        self.party = Party.objects.create(legal_name="Addon Co", party_type=PartyType.ORGANIZATION)

    def test_inactive_zero_rate_no_charge_active_with_rate_charges(self):
        lease = Lease.objects.create(
            code="L-ADDON",
            party=self.party,
            space=self.space,
            status=LeaseStatus.ACTIVE,
            rent=Decimal("1000"),
            rent_rate_per_m2=Decimal("10"),
            deposit=Decimal("2000"),
            billing_active=True,
            start_date=timezone.localdate().replace(day=1),
        )
        inactive = LeaseAddon.objects.create(
            lease=lease, code="cleaning", label="Təmizlik", rate_per_m2=Decimal("0"), is_active=False
        )
        generate_monthly_lease_charges(as_of=timezone.localdate())
        self.assertFalse(
            Charge.objects.filter(lease=lease, source=ChargeSource.ADDITIONAL, description__icontains="Təmizlik").exists()
        )
        inactive.rate_per_m2 = Decimal("2")
        inactive.is_active = True
        inactive.save()
        # Force new period by clearing existing ADDITIONAL or use next month — regenerate same period skips duplicates
        Charge.objects.filter(lease=lease, source=ChargeSource.ADDITIONAL).delete()
        # Monthly gen dedupes by period+source+description — delete rent too to re-run cleanly for addon only path
        stats = generate_monthly_lease_charges(as_of=timezone.localdate())
        self.assertGreaterEqual(stats["created"], 1)
        self.assertTrue(
            Charge.objects.filter(
                lease=lease, source=ChargeSource.ADDITIONAL, description__icontains="Təmizlik"
            ).exists()
        )


class Phase436PortalInvoiceIsolationTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.co_a = ResidentCompany.objects.create(name="InvA", slug="inv-a-436", voen="111")
        self.co_b = ResidentCompany.objects.create(name="InvB", slug="inv-b-436", voen="222")
        self.party_a = Party.objects.create(
            legal_name="InvA", party_type=PartyType.ORGANIZATION, legacy_resident_company=self.co_a
        )
        self.party_b = Party.objects.create(
            legal_name="InvB", party_type=PartyType.ORGANIZATION, legacy_resident_company=self.co_b
        )
        self.user_a = User.objects.create_user(
            username="inv-a",
            email="inva@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=self.co_a,
        )
        ensure_portal_membership(self.user_a, self.co_a)
        self.ch_a = Charge.objects.create(
            party=self.party_a,
            source=ChargeSource.RENT,
            description="A rent",
            amount=Decimal("100"),
            currency="AZN",
            period_start=timezone.localdate().replace(day=1),
            period_end=timezone.localdate(),
        )
        self.ch_b = Charge.objects.create(
            party=self.party_b,
            source=ChargeSource.RENT,
            description="B rent",
            amount=Decimal("200"),
            currency="AZN",
            period_start=timezone.localdate().replace(day=1),
            period_end=timezone.localdate(),
        )
        self.inv_a = generate_invoice_from_charges(self.party_a, [self.ch_a.pk])
        self.inv_b = generate_invoice_from_charges(self.party_b, [self.ch_b.pk])
        confirm_invoice(self.inv_a)
        confirm_invoice(self.inv_b)

    def test_resident_cannot_see_other_company_invoice(self):
        client = Client()
        client.force_login(self.user_a)
        client.post(reverse("portal:choose_companies"), {"choice": str(self.co_a.pk)})
        resp = client.get(reverse("portal:invoices"))
        self.assertEqual(resp.status_code, 200)
        rows = resp.context["invoice_rows"]
        ids = {row["invoice"].pk for row in rows}
        self.assertIn(self.inv_a.pk, ids)
        self.assertNotIn(self.inv_b.pk, ids)
