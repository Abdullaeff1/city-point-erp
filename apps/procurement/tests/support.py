"""Shared test helpers for the mandatory-Management procurement policy.

Policy under test (see ``ProcurementService``):
* ``approve_pr`` never self-authorizes — every PR escalates to Management.
* A priced PO needs a matching, Management-approved ``procurement.commitment``
  (Admin has no bypass).
* Goods receipt requires an issued (priced, SENT) PO.

These helpers walk the *real* escalation path and then record the Management
decision, so positive-path fixtures stay realistic instead of bypassing policy.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.procurement.models import PurchaseRequest
from apps.procurement.services import (
    WF_PROCUREMENT_COMMITMENT,
    WF_PROCUREMENT_PR,
    ProcurementService,
)
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()

_MGMT_USERNAME = "tst-mgmt-approver"


def management_approver():
    """Return a dedicated Management user used only to record decisions in tests."""
    user, _ = User.objects.get_or_create(
        username=_MGMT_USERNAME,
        defaults={
            "email": f"{_MGMT_USERNAME}@test.az",
            "role": Role.MANAGEMENT,
            "is_staff": True,
        },
    )
    return user


def approve_pr_via_management(pr: PurchaseRequest, *, actor, mgmt=None) -> PurchaseRequest:
    """Escalate ``pr`` as ``actor`` and approve it as Management (process-only decision)."""
    mgmt = mgmt or management_approver()
    try:
        ProcurementService.approve_pr(pr, actor=actor)
    except DomainError:
        pass  # expected: escalation raises after persisting the request
    ct = ContentType.objects.get_for_model(PurchaseRequest)
    req = ApprovalRequest.objects.get(
        workflow_code=WF_PROCUREMENT_PR,
        status=ApprovalStatus.PENDING,
        entity_type=ct,
        entity_id=pr.pk,
    )
    ProcurementService.decide_management_pr(req, approved=True, actor=mgmt, comment="test")
    pr.refresh_from_db()
    return pr


def approve_pending_commitment(pr: PurchaseRequest, *, mgmt=None) -> ApprovalRequest:
    """Approve the single pending commitment request for ``pr`` as Management."""
    mgmt = mgmt or management_approver()
    ct = ContentType.objects.get_for_model(PurchaseRequest)
    req = (
        ApprovalRequest.objects.filter(
            workflow_code=WF_PROCUREMENT_COMMITMENT,
            status=ApprovalStatus.PENDING,
            entity_type=ct,
            entity_id=pr.pk,
        )
        .order_by("-id")
        .first()
    )
    if req is None:
        raise AssertionError("No pending procurement commitment to approve.")
    ApprovalService.decide(req, approved=True, decided_by=mgmt, comment="test")
    return req


def approve_all_pending_commitments(pr: PurchaseRequest, *, mgmt=None) -> int:
    """Approve every pending commitment request for ``pr`` (multi-supplier awards)."""
    mgmt = mgmt or management_approver()
    ct = ContentType.objects.get_for_model(PurchaseRequest)
    pending = ApprovalRequest.objects.filter(
        workflow_code=WF_PROCUREMENT_COMMITMENT,
        status=ApprovalStatus.PENDING,
        entity_type=ct,
        entity_id=pr.pk,
    ).order_by("id")
    count = 0
    for req in pending:
        ApprovalService.decide(req, approved=True, decided_by=mgmt, comment="test")
        count += 1
    return count


def issue_priced_po(
    pr: PurchaseRequest,
    *,
    supplier,
    unit_price,
    actor,
    line_qtys=None,
    mgmt=None,
):
    """Create a priced (SENT) PO through the escalate → Management approve → issue path."""
    kwargs = dict(
        supplier_party=supplier,
        actor=actor,
        unit_price=unit_price,
        line_qtys=line_qtys,
    )
    try:
        return ProcurementService.create_po_from_pr(pr, **kwargs)
    except DomainError:
        pass  # expected: commitment escalation persisted, PO not issued
    approve_pending_commitment(pr, mgmt=mgmt)
    return ProcurementService.create_po_from_pr(pr, **kwargs)


def issue_quote_po(quote, *, actor, mgmt=None):
    """Select an RFQ quote → Management approves the commitment → PO issued."""
    try:
        return ProcurementService.select_rfq_quote_and_create_po(quote, actor=actor)
    except DomainError:
        pass
    approve_pending_commitment(quote.rfq.pr, mgmt=mgmt)
    return ProcurementService.select_rfq_quote_and_create_po(quote, actor=actor)
