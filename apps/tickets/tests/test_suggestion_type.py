from django.test import TestCase

from apps.erp.forms import PortalTicketForm, StaffTicketForm
from apps.tickets.models import TicketCategory, TicketSubcategory, TicketType


class SuggestionTicketTypeTests(TestCase):
    def test_request_type_includes_suggestion(self):
        self.assertEqual(TicketType.SUGGESTION.label, "Təklif")
        rendered = str(StaffTicketForm()["ticket_type"])
        self.assertIn("Təklif", rendered)

    def test_portal_description_is_optional(self):
        category = TicketCategory.objects.create(name="Təhlükəsizlik", slug="security-opt")
        subcategory = TicketSubcategory.objects.create(
            category=category,
            name="Digər",
            slug="security-other-opt",
            requires_description_min=20,
        )
        form = PortalTicketForm(
            data={
                "ticket_type": "incident",
                "category": category.pk,
                "subcategory": subcategory.pk,
                "description": "",
            }
        )
        rendered = str(form["description"])
        self.assertNotIn("required", rendered)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["description"], "")
