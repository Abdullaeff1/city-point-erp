from django.test import SimpleTestCase, TestCase

from apps.core.search import filter_text_search, fold_search
from apps.residents.models import ResidentCompany, ResidentEmployee


class FoldSearchTests(SimpleTestCase):
    def test_ascii_case(self):
        self.assertEqual(fold_search("Ali"), fold_search("ALI"))
        self.assertEqual(fold_search("Ali"), "ali")

    def test_azerbaijani_i(self):
        self.assertEqual(fold_search("İnara"), "inara")
        self.assertEqual(fold_search("INARA"), "inara")
        self.assertEqual(fold_search("ınara"), "inara")
        self.assertEqual(fold_search("İnara"), fold_search("inara"))

    def test_whitespace(self):
        self.assertEqual(fold_search("  Ali   Vəli "), "ali vəli")


class FilterTextSearchTests(TestCase):
    def test_finds_dotted_capital_i(self):
        company = ResidentCompany.objects.create(name="Test Co", slug="test-co-search")
        emp = ResidentEmployee.objects.create(
            company=company,
            full_name="İnara Test",
            is_active=True,
        )
        found = filter_text_search(
            ResidentEmployee.objects.all(), "inara", "full_name"
        )
        self.assertIn(emp, found)
        found_upper = filter_text_search(
            ResidentEmployee.objects.all(), "İNARA", "full_name"
        )
        self.assertIn(emp, found_upper)
