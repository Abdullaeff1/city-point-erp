"""Phase 4.1 Scope B — Approval decision → requester notification (decision-unique)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.comms.models import Notification
from apps.core import events as bus
from apps.core.event_handlers import register_default_handlers
from apps.workflows.models import ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


class Phase41ApprovalDecisionNotifyTests(TestCase):
    def setUp(self):
        bus.clear_handlers()
        register_default_handlers()
        self.requester = User.objects.create_user(
            username="p41-req",
            email="p41-req@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.decider = User.objects.create_user(
            username="p41-dec",
            email="p41-dec@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )

    def tearDown(self):
        bus.clear_handlers()
        register_default_handlers()

    def test_decide_notifies_requester(self):
        req = ApprovalService.request(
            workflow_code="p41.lease",
            requested_by=self.requester,
            payload={"n": 1},
        )
        ApprovalService.decide(req, approved=True, decided_by=self.decider, comment="ok")
        req.refresh_from_db()
        stamp = req.decided_at.isoformat()
        key = f"approval.decided.{req.pk}.{ApprovalStatus.APPROVED}.{stamp}"
        notes = Notification.objects.filter(user=self.requester, event_key=key)
        self.assertEqual(notes.count(), 1)
        self.assertIn("təsdiqləndi", notes.get().message)

    def test_same_decision_dedupes_notification(self):
        req = ApprovalService.request(
            workflow_code="p41.dedupe",
            requested_by=self.requester,
        )
        ApprovalService.decide(req, approved=False, decided_by=self.decider, comment="no")
        req.refresh_from_db()
        stamp = req.decided_at.isoformat()
        key = f"approval.decided.{req.pk}.{ApprovalStatus.REJECTED}.{stamp}"
        self.assertEqual(Notification.objects.filter(user=self.requester, event_key=key).count(), 1)
        # Re-emit identical decision event — must not create a second note
        bus.emit(
            bus.APPROVAL_DECIDED,
            payload={
                "approval_id": req.pk,
                "workflow_code": req.workflow_code,
                "status": req.status,
            },
            event_key=key,
        )
        self.assertEqual(Notification.objects.filter(user=self.requester, event_key=key).count(), 1)

    def test_reconsideration_uses_new_decision_key(self):
        """If workflow is reopened to PENDING and decided again, requester is notified again."""
        req = ApprovalService.request(
            workflow_code="p41.reopen",
            requested_by=self.requester,
        )
        ApprovalService.decide(req, approved=True, decided_by=self.decider, comment="first")
        req.refresh_from_db()
        first_stamp = req.decided_at.isoformat()
        first_key = f"approval.decided.{req.pk}.{ApprovalStatus.APPROVED}.{first_stamp}"
        self.assertEqual(Notification.objects.filter(user=self.requester, event_key=first_key).count(), 1)

        # Simulate reopen/reconsideration (no product reopen API yet — reset to PENDING).
        req.status = ApprovalStatus.PENDING
        req.decided_at = None
        req.decided_by = None
        req.comment = ""
        req.save(update_fields=["status", "decided_at", "decided_by", "comment", "updated_at"])

        ApprovalService.decide(req, approved=False, decided_by=self.decider, comment="second")
        req.refresh_from_db()
        second_stamp = req.decided_at.isoformat()
        second_key = f"approval.decided.{req.pk}.{ApprovalStatus.REJECTED}.{second_stamp}"
        self.assertNotEqual(first_key, second_key)
        self.assertEqual(Notification.objects.filter(user=self.requester, event_key=second_key).count(), 1)
        self.assertEqual(
            Notification.objects.filter(user=self.requester, event_key__startswith=f"approval.decided.{req.pk}.").count(),
            2,
        )
        self.assertIn("rədd edildi", Notification.objects.get(event_key=second_key).message)
