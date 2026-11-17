from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.crm.mapping import (
    infer_outcome_from_notes,
    map_pipeline_stage,
    map_source,
    parse_area_range,
)
from apps.crm.models import Lead, OfferStatus, Outcome, PipelineStage, Qualification
from apps.crm.services import (
    CrmLeadService,
    CrmOfferService,
    CrmOpportunityService,
    LeaseApplicationService,
    compose_bank_details,
)
from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyStatus, PartyType

User = get_user_model()


class CrmMappingParseTests(TestCase):
    def test_source_typo_and_stage_combo(self):
        code, note = map_source("Soyuq zənqlər")
        self.assertEqual(code, "cold_call")
        self.assertEqual(note, "")
        self.assertEqual(map_pipeline_stage("Yeni sorğu/İşlənilir"), PipelineStage.WORKING)
        self.assertEqual(map_pipeline_stage("Sahəyə baxış keçirilib"), PipelineStage.VIEWING_COMPLETED)

    def test_area_range_and_single(self):
        mn, mx, note = parse_area_range("150-200 kv")
        self.assertEqual(mn, Decimal("150"))
        self.assertEqual(mx, Decimal("200"))
        mn, mx, note = parse_area_range("175 kv  7-ci m")
        self.assertEqual(mn, Decimal("175"))
        self.assertEqual(mx, Decimal("175"))
        self.assertIn("7", note)

    def test_infer_outcome(self):
        self.assertEqual(infer_outcome_from_notes("Qiymət bahadır"), Outcome.PRICE)
        self.assertEqual(infer_outcome_from_notes("Sahə uyğun deyil"), Outcome.AREA)
        self.assertEqual(infer_outcome_from_notes("yanlış sorğu"), Outcome.INVALID_REQUEST)
        self.assertEqual(
            infer_outcome_from_notes("Qiymət bahadır", existing=Outcome.NO_RESPONSE),
            Outcome.NO_RESPONSE,
        )


class CrmLeaseFormFieldsTests(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user(
            username="sales_form", email="sf@test.az", password="x", role=Role.SALES, is_staff=True
        )
        self.manager = User.objects.create_user(
            username="mgr_form", email="mf@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )

    def test_bank_requisites_snapshot(self):
        lead = CrmLeadService.create_lead(
            actor=self.sales,
            data={"company_name": "Form Co", "phone": "555", "qualification": Qualification.POTENTIAL},
            notify=False,
        )
        CrmLeadService.update_lead(
            lead, actor=self.sales, data={"qualification": Qualification.POTENTIAL}
        )
        opp = CrmOpportunityService.create_from_lead(lead, actor=self.sales)
        party = Party.objects.create(
            legal_name="Form Co MMC",
            party_type=PartyType.ORGANIZATION,
            status=PartyStatus.PROSPECT,
        )
        PartyRole.objects.create(party=party, role=PartyRoleCode.PROSPECT, is_primary=True)
        opp.party = party
        opp.save()
        offer = CrmOfferService.create_offer(
            actor=self.sales, opportunity=opp, party=party, area_m2=Decimal("50")
        )
        offer.status = OfferStatus.SENT
        offer.save()
        app = LeaseApplicationService.create_from_offer(offer, actor=self.sales)
        self.assertIsNotNone(app.application_date)
        LeaseApplicationService.update_draft(
            app,
            actor=self.sales,
            data={
                "extra_notes": "Əlavə",
                "is_legal_entity": True,
                "bank_requisites": {
                    "currency": "AZN",
                    "bank_name": "Kapital",
                    "branch_code": "123",
                    "voen": "100",
                    "swift": "SWIFT",
                    "current_account": "MH1",
                    "correspondent": "HH1",
                },
                "attachment_checklist": {"voen": True, "registry": True, "bank": True},
            },
        )
        app.refresh_from_db()
        self.assertEqual(app.extra_notes, "Əlavə")
        self.assertIn("Kapital", app.bank_details)
        self.assertEqual(app.bank_requisites.get("swift"), "SWIFT")
        self.assertEqual(app.form_snapshot.get("extra_notes"), "Əlavə")
        self.assertTrue(app.form_snapshot.get("is_legal_entity"))
        self.assertIn("Valyuta", compose_bank_details(app.bank_requisites))


class CrmImportCommandTests(TestCase):
    def test_dry_run_and_apply_one_row(self):
        from io import StringIO
        from pathlib import Path

        from django.core.management import call_command
        from openpyxl import Workbook

        path = Path("/tmp/crm_leads_fixture.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.title = "Ümumi müştərilər"
        ws.append(["", "№", "Şirkət adı", "Əlaqəli şəxs", "Əlaqə Nöm", "Müraciət Tarixi", "Lid mənbəyi", "Tələb olunan sahə", "Seçim edilən sahə", "Qiymət ", "Lid statusu", "Nəticə", "Sorğu statusu", "Qeydlər"])
        ws.append(["", "1", "Import Co", "Ali", "050-111-22-33", "01.04.2026", "Soyuq zənqlər", "80-100 kv", "90 kv", "33 AZN+ƏDV", "Yeni sorğu/İşlənilir", "", "Açıqdır", "Qiymət bahadır test"])
        wb.save(path)

        out = StringIO()
        call_command("import_crm_leads_xlsx", file=str(path), stdout=out)
        self.assertIn("DRY-RUN", out.getvalue())
        self.assertEqual(Lead.objects.count(), 0)

        out2 = StringIO()
        call_command("import_crm_leads_xlsx", file=str(path), apply=True, stdout=out2)
        self.assertIn("APPLY", out2.getvalue())
        lead = Lead.objects.get(external_id="xlsx:umumi-musteriler:1")
        self.assertEqual(lead.company_name, "Import Co")
        self.assertEqual(lead.source, "cold_call")
        self.assertEqual(lead.min_area_m2, Decimal("80"))
        self.assertEqual(lead.max_area_m2, Decimal("100"))
        self.assertEqual(lead.outcome, Outcome.PRICE)
        self.assertTrue(lead.activities.filter(activity_type="note").exists())

        # idempotent
        call_command("import_crm_leads_xlsx", file=str(path), apply=True, stdout=StringIO())
        self.assertEqual(Lead.objects.filter(external_id="xlsx:umumi-musteriler:1").count(), 1)
