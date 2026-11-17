from django.test import TestCase

from apps.audit.models import AuditLog
from apps.parties.dedupe import (
    build_duplicate_report,
    find_duplicate_companies_by_voen,
    find_duplicate_parties_by_tax_id,
    normalize_tax_id,
)
from apps.parties.services import PartyService
from apps.residents.company_sync import save_resident_company
from apps.residents.models import ResidentCompany


class NormalizeTests(TestCase):
    def test_tax_id(self):
        self.assertEqual(normalize_tax_id(" 123-456 "), "123456")


class DedupeReportTests(TestCase):
    def test_duplicate_voen_and_party_tax(self):
        a = ResidentCompany.objects.create(name="Alpha MMC", slug="alpha-m1", voen="1112223331")
        b = ResidentCompany.objects.create(name="Alpha Dup", slug="alpha-m1-dup", voen="111-222-3331")
        PartyService.upsert_from_resident_company(a, audit=False)
        PartyService.upsert_from_resident_company(b, audit=False)

        voen_dups = find_duplicate_companies_by_voen()
        self.assertTrue(any(d["key"] == "1112223331" for d in voen_dups))

        tax_dups = find_duplicate_parties_by_tax_id()
        self.assertTrue(any(d["key"] == "1112223331" for d in tax_dups))

        report = build_duplicate_report()
        self.assertIn("company_voen", report)
        self.assertGreaterEqual(len(report["company_voen"]), 1)


class PartySyncUnificationTests(TestCase):
    def test_save_company_uses_party_service_fields(self):
        company = ResidentCompany(
            name="Sync Co",
            slug="sync-co-m1",
            voen="9998887771",
            contact_email="a@example.com",
            phone="+994501112233",
        )
        save_resident_company(company, create=True, audit=True)
        party = company.party
        self.assertEqual(party.tax_id, "9998887771")
        self.assertEqual(party.contact_phone, "+994501112233")
        self.assertEqual(party.contact_email, "a@example.com")

    def test_upsert_writes_audit_when_enabled(self):
        company = ResidentCompany.objects.create(name="Aud Co", slug="aud-co-m1", voen="555")
        PartyService.upsert_from_resident_company(company, audit=True)
        self.assertTrue(AuditLog.objects.filter(action="party.upserted").exists())
