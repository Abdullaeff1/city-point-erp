from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.core import events as bus
from apps.core.event_handlers import register_default_handlers
from apps.parties.resolvers import party_for_company
from apps.parties.services import PartyService
from apps.residents.models import ResidentCompany
from apps.workflows.services import ApprovalService

User = get_user_model()


class DomainEventTests(TestCase):
    def setUp(self):
        bus.clear_handlers()
        register_default_handlers()

    def tearDown(self):
        bus.clear_handlers()
        register_default_handlers()

    def test_emit_writes_audit(self):
        bus.emit(bus.TICKET_CREATED, payload={"ticket_id": None, "entity_model": "ticket", "code": "T-TEST"})
        self.assertTrue(AuditLog.objects.filter(action=bus.TICKET_CREATED).exists())


class PartyResolverTests(TestCase):
    def test_party_for_company_ensure(self):
        company = ResidentCompany.objects.create(name="Link Co", slug="link-co")
        party = party_for_company(company, ensure=True)
        self.assertIsNotNone(party)
        self.assertEqual(party.legacy_resident_company_id, company.pk)
        again = party_for_company(company, ensure=False)
        self.assertEqual(again.pk, party.pk)


class ApprovalServiceTests(TestCase):
    def setUp(self):
        bus.clear_handlers()
        register_default_handlers()
        self.user = User.objects.create_user(
            username="approver",
            email="approver@citypoint.az",
            password="SecurePass123!",
        )

    def tearDown(self):
        bus.clear_handlers()
        register_default_handlers()

    def test_request_and_approve(self):
        req = ApprovalService.request(workflow_code="lease.activate", requested_by=self.user, payload={"x": 1})
        self.assertEqual(req.status, "pending")
        ApprovalService.decide(req, approved=True, decided_by=self.user, comment="ok")
        req.refresh_from_db()
        self.assertEqual(req.status, "approved")
        self.assertTrue(AuditLog.objects.filter(action=bus.APPROVAL_DECIDED).exists())
