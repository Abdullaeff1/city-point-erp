from django.test import TestCase

from apps.property.models import Building, Floor, Space
from apps.residents.models import ResidentCompany


class SpaceAreaCodeTests(TestCase):
    def test_company_space_code_uses_floor_and_sqm(self):
        building = Building.objects.create(code="CP", name="City Point")
        floor = Floor.objects.create(building=building, code="F10", name="10-cu mərtəbə")
        company = ResidentCompany.objects.create(name="ASBC", slug="asbc", status="active")
        space = Space.objects.create(
            code="CP-F08-OFF-801",
            name="801",
            floor=floor,
            resident=company,
            area_m2="232",
        )
        self.assertEqual(space.area_code, "CP/F10/232")
        self.assertEqual(space.short_label, "CP/F10/232")
        self.assertEqual(str(space), "CP/F10/232")
        self.assertNotIn("801", space.short_label)
