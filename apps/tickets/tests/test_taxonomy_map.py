from django.test import TestCase

from apps.erp.forms import PortalTicketForm, StaffTicketForm
from apps.tickets.models import RoutingRule, TicketCategory, TicketSubcategory, TicketType
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.taxonomy_map import (
    allowed_category_slugs,
    categories_for_ticket_type,
    category_allowed_for_type,
    ticket_type_choices_for_forms,
)


class TaxonomyMapTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_ticket_taxonomy()

    def test_form_choices_exclude_suggestion(self):
        values = [v for v, _ in ticket_type_choices_for_forms()]
        self.assertNotIn(TicketType.SUGGESTION, values)
        self.assertIn(TicketType.INCIDENT, values)
        rendered = str(StaffTicketForm()["ticket_type"])
        self.assertNotIn("Təklif", rendered)
        self.assertNotIn("suggestion", rendered)

    def test_incident_slugs(self):
        self.assertEqual(
            allowed_category_slugs(TicketType.INCIDENT),
            ("technical", "cleaning", "security", "parking", "other"),
        )
        slugs = set(categories_for_ticket_type(TicketType.INCIDENT).values_list("slug", flat=True))
        self.assertEqual(slugs, set(allowed_category_slugs(TicketType.INCIDENT)))

    def test_service_request_and_commercial_slugs(self):
        self.assertEqual(
            set(allowed_category_slugs(TicketType.SERVICE_REQUEST)),
            {"technical", "security", "cleaning", "other"},
        )
        self.assertEqual(
            set(allowed_category_slugs(TicketType.COMMERCIAL)),
            {"commercial-space", "lease", "billing", "administration", "other"},
        )

    def test_complaint_allows_all_active(self):
        self.assertIsNone(allowed_category_slugs(TicketType.COMPLAINT))
        all_active = set(
            TicketCategory.objects.filter(is_active=True).values_list("slug", flat=True)
        )
        self.assertEqual(
            set(categories_for_ticket_type(TicketType.COMPLAINT).values_list("slug", flat=True)),
            all_active,
        )

    def test_wo_eligible_all_after_seed(self):
        self.assertTrue(RoutingRule.objects.exists())
        self.assertFalse(RoutingRule.objects.filter(wo_eligible=False).exists())

    def test_incident_rejects_billing_category(self):
        billing = TicketCategory.objects.get(slug="billing")
        self.assertFalse(category_allowed_for_type(TicketType.INCIDENT, billing))
        technical = TicketCategory.objects.get(slug="technical")
        sub = TicketSubcategory.objects.filter(category=technical, is_active=True).first()
        form = PortalTicketForm(
            data={
                "ticket_type": TicketType.INCIDENT,
                "category": billing.pk,
                "subcategory": sub.pk,
                "description": "test",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("category", form.errors)
