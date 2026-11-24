"""Reusable approval engine — one implementation for lease, PR, documents, etc."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core import events as bus
from apps.core.services import DomainError, Service
from apps.workflows.models import ApprovalRequest, ApprovalStatus


class ApprovalService(Service):
    @classmethod
    @transaction.atomic
    def request(
        cls,
        *,
        workflow_code: str,
        requested_by=None,
        entity=None,
        payload: dict | None = None,
    ) -> ApprovalRequest:
        cls.require(bool(workflow_code.strip()), "workflow_code tələb olunur.")
        req = ApprovalRequest.objects.create(
            workflow_code=workflow_code.strip(),
            status=ApprovalStatus.PENDING,
            requested_by=requested_by,
            entity=entity,
            payload=payload or {},
        )
        bus.emit(
            bus.APPROVAL_REQUESTED,
            payload={
                "approval_id": req.pk,
                "workflow_code": req.workflow_code,
                "entity_model": "approval",
            },
            actor=requested_by,
            event_key=f"approval.requested.{req.pk}",
        )
        return req

    @classmethod
    @transaction.atomic
    def decide(
        cls,
        request: ApprovalRequest,
        *,
        approved: bool,
        decided_by=None,
        comment: str = "",
    ) -> ApprovalRequest:
        locked = ApprovalRequest.objects.select_for_update().get(pk=request.pk)
        cls.require(
            locked.status == ApprovalStatus.PENDING,
            "Yalnız gözləyən sorğu qərar verilə bilər.",
        )
        if (
            decided_by is not None
            and locked.requested_by_id
            and getattr(decided_by, "pk", None) == locked.requested_by_id
        ):
            raise DomainError("Öz sorğunuzu təsdiq edə bilməzsiniz.")
        locked.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        locked.decided_by = decided_by
        locked.decided_at = timezone.now()
        locked.comment = (comment or "")[:2000]
        locked.save(update_fields=["status", "decided_by", "decided_at", "comment", "updated_at"])
        # Decision-unique key so a later reopen/reconsider can notify again.
        stamp = locked.decided_at.isoformat() if locked.decided_at else str(locked.pk)
        bus.emit(
            bus.APPROVAL_DECIDED,
            payload={
                "approval_id": locked.pk,
                "workflow_code": locked.workflow_code,
                "status": locked.status,
                "entity_model": "approval",
                "requested_by_id": locked.requested_by_id,
            },
            actor=decided_by,
            event_key=f"approval.decided.{locked.pk}.{locked.status}.{stamp}",
        )
        request.status = locked.status
        request.decided_by = locked.decided_by
        request.decided_at = locked.decided_at
        request.comment = locked.comment
        return locked

    @classmethod
    @transaction.atomic
    def cancel(cls, request: ApprovalRequest, *, actor=None, comment: str = "") -> ApprovalRequest:
        locked = ApprovalRequest.objects.select_for_update().get(pk=request.pk)
        cls.require(
            locked.status == ApprovalStatus.PENDING,
            "Yalnız gözləyən sorğu ləğv edilə bilər.",
        )
        locked.status = ApprovalStatus.CANCELLED
        locked.decided_by = actor
        locked.decided_at = timezone.now()
        if comment:
            locked.comment = comment[:2000]
        locked.save(update_fields=["status", "decided_by", "decided_at", "comment", "updated_at"])
        request.status = locked.status
        request.decided_by = locked.decided_by
        request.decided_at = locked.decided_at
        request.comment = locked.comment
        return locked
