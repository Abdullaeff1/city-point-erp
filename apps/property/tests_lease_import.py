from decimal import Decimal

from django.test import TestCase

from apps.property.lease_space_import import (
    _fold,
    _split_combo,
    floor_code_for,
    resolve_company,
    STATUS_MAP,
)
from apps.property.models import CommercialStatus, Occupancy
from apps.residents.models import ResidentCompany


class LeaseSpaceImportHelpersTests(TestCase):
    def test_status_fold_matches_excel_labels(self):
        self.assertEqual(
            STATUS_MAP[_fold("İcarədə")],
            (Occupancy.ACTIVE_LEASE, CommercialStatus.ACTIVE),
        )
        self.assertEqual(
            STATUS_MAP[_fold("Boş sahə")],
            (Occupancy.VACANT, CommercialStatus.VACANT),
        )

    def test_floor_codes(self):
        self.assertEqual(floor_code_for(-1), "B01")
        self.assertEqual(floor_code_for(8), "F08")
        self.assertEqual(floor_code_for("7"), "F07")

    def test_split_combo(self):
        parts = _split_combo("SİMPLEX (338 m2) & ST Mark (18 m2) & Qala Express (18 m2)")
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0][0], "SİMPLEX")
        self.assertEqual(parts[0][1], Decimal("338"))
        self.assertEqual(parts[2][0], "Qala Express")

    def test_alias_resolves_existing_company(self):
        company = ResidentCompany.objects.create(name="L.B.Audit", slug="lbaudit-test")
        from apps.property import lease_space_import as mod

        index = mod._company_index()
        hit = resolve_company("LB AUDİT (INVEST FINANS)", index, create_missing=False)
        self.assertEqual(hit.pk, company.pk)
