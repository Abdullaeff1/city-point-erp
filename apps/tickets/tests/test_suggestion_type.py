from django.test import TestCase

from apps.erp.forms import PortalTicketForm, StaffTicketForm
from apps.tickets.models import TicketCategory, TicketSubcategory, TicketType
from apps.tickets.taxonomy_map import ticket_type_choices_for_forms


class SuggestionTicketTypeTests(TestCase):
    def test_suggestion_exists_on_model_but_not_in_forms(self):
        self.assertEqual(TicketType.SUGGESTION.label, "Təklif")
        values = [v for v, _ in ticket_type_choices_for_forms()]
        self.assertNotIn(TicketType.SUGGESTION, values)
        self.assertNotIn("Təklif", str(StaffTicketForm()["ticket_type"]))
        self.assertNotIn("Təklif", str(PortalTicketForm()["ticket_type"]))

    def test_portal_description_is_optional(self):
        # slug must be allowed for incident (A.2 type→category map)
        category = TicketCategory.objects.create(name="Təhlükəsizlik", slug="security")
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
