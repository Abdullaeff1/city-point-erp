"""Reusable approval engine — one implementation for lease, PR, documents, etc."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core import events as bus
from apps.core.services import Service
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
        cls.require(request.status == ApprovalStatus.PENDING, "Yalnız gözləyən sorğu qərar verilə bilər.")
        request.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        request.decided_by = decided_by
        request.decided_at = timezone.now()
        request.comment = (comment or "")[:2000]
        request.save(update_fields=["status", "decided_by", "decided_at", "comment", "updated_at"])
        bus.emit(
            bus.APPROVAL_DECIDED,
            payload={
                "approval_id": request.pk,
                "workflow_code": request.workflow_code,
                "status": request.status,
                "entity_model": "approval",
            },
            actor=decided_by,
        )
        return request

    @classmethod
    @transaction.atomic
    def cancel(cls, request: ApprovalRequest, *, actor=None, comment: str = "") -> ApprovalRequest:
        cls.require(request.status == ApprovalStatus.PENDING, "Yalnız gözləyən sorğu ləğv edilə bilər.")
        request.status = ApprovalStatus.CANCELLED
        request.decided_by = actor
        request.decided_at = timezone.now()
        if comment:
            request.comment = comment[:2000]
        request.save(update_fields=["status", "decided_by", "decided_at", "comment", "updated_at"])
        return request
