"""Default domain-event handlers (audit + light notifications)."""

from __future__ import annotations

from apps.audit.services import log_action
from apps.core import events as bus


def _audit_handler(event: bus.DomainEvent) -> None:
    from django.contrib.auth import get_user_model

    User = get_user_model()
    actor = None
    if event.actor_id:
        actor = User.objects.filter(pk=event.actor_id).first()
    entity = None
    model_hint = (event.payload.get("entity_model") or "").strip()
    # Prefer model hint + matching id so POReceived binds to PurchaseOrder, not PR.
    typed_id = None
    if model_hint == "ticket":
        typed_id = event.payload.get("ticket_id")
    elif model_hint == "visit":
        typed_id = event.payload.get("visit_id")
    elif model_hint == "lease":
        typed_id = event.payload.get("lease_id")
    elif model_hint == "approval":
        typed_id = event.payload.get("approval_id") or event.payload.get("request_id")
    elif model_hint == "work_order":
        typed_id = event.payload.get("work_order_id")
    elif model_hint in {"purchase_order", "po"}:
        typed_id = event.payload.get("po_id")
    elif model_hint in {"purchase_request", "pr"}:
        typed_id = event.payload.get("pr_id")
    elif model_hint == "warehouse_issue":
        typed_id = event.payload.get("issue_id")

    pk = typed_id or (
        event.payload.get("ticket_id")
        or event.payload.get("visit_id")
        or event.payload.get("lease_id")
        or event.payload.get("work_order_id")
        or event.payload.get("approval_id")
        or event.payload.get("po_id")
        or event.payload.get("pr_id")
        or event.payload.get("issue_id")
    )
    if model_hint and pk:
        if model_hint == "ticket":
            from apps.tickets.models import Ticket

            entity = Ticket.objects.filter(pk=pk).first()
        elif model_hint == "visit":
            from apps.reception.models import GuestVisit

            entity = GuestVisit.objects.filter(pk=pk).first()
        elif model_hint == "lease":
            from apps.leases.models import Lease

            entity = Lease.objects.filter(pk=pk).first()
        elif model_hint == "approval":
            from apps.workflows.models import ApprovalRequest

            entity = ApprovalRequest.objects.filter(pk=pk).first()
        elif model_hint == "work_order":
            from apps.maintenance.models import WorkOrder

            entity = WorkOrder.objects.filter(pk=pk).first()
        elif model_hint in {"purchase_order", "po"}:
            from apps.procurement.models import PurchaseOrder

            entity = PurchaseOrder.objects.filter(pk=pk).first()
        elif model_hint in {"purchase_request", "pr"}:
            from apps.procurement.models import PurchaseRequest

            entity = PurchaseRequest.objects.filter(pk=pk).first()
        elif model_hint == "warehouse_issue":
            from apps.warehouse.models import WarehouseIssue

            entity = WarehouseIssue.objects.filter(pk=pk).first()
    elif event.payload.get("po_id"):
        from apps.procurement.models import PurchaseOrder

        entity = PurchaseOrder.objects.filter(pk=event.payload["po_id"]).first()
    log_action(
        action=event.name,
        actor=actor,
        entity=entity,
        new_values=event.payload,
        source="domain_event",
        correlation_id=event.correlation_id,
    )


def _ticket_created_notify(event: bus.DomainEvent) -> None:
    ticket_id = event.payload.get("ticket_id")
    if not ticket_id:
        return
    from apps.comms.services import notify_in_app
    from apps.tickets.models import Ticket

    ticket = Ticket.objects.select_related("assignee", "company").filter(pk=ticket_id).first()
    if not ticket or not ticket.assignee_id:
        return
    notify_in_app(
        user=ticket.assignee,
        message=f"Yeni ticket: {ticket.code}",
        ticket=ticket,
        event_key=f"ticket.created.{ticket.pk}",
    )


def _ticket_assigned_notify(event: bus.DomainEvent) -> None:
    ticket_id = event.payload.get("ticket_id")
    if not ticket_id:
        return
    from apps.comms.services import notify_in_app
    from apps.tickets.models import Ticket

    ticket = Ticket.objects.select_related("assignee").filter(pk=ticket_id).first()
    if not ticket or not ticket.assignee_id:
        return
    notify_in_app(
        user=ticket.assignee,
        message=f"Ticket təyin olundu: {ticket.code}",
        ticket=ticket,
        event_key=f"ticket.assigned.{ticket.pk}.{ticket.assignee_id}",
    )


def _ticket_resolved_notify(event: bus.DomainEvent) -> None:
    ticket_id = event.payload.get("ticket_id")
    if not ticket_id:
        return
    from apps.comms.services import notify_in_app
    from apps.tickets.models import Ticket

    ticket = Ticket.objects.select_related("requester").filter(pk=ticket_id).first()
    if not ticket or not ticket.requester_id:
        return
    # Include status-event id so a genuine second resolve after reopen is not suppressed.
    occurrence = event.payload.get("status_event_id") or event.correlation_id or "1"
    notify_in_app(
        user=ticket.requester,
        message=f"Ticket həll olundu: {ticket.code}",
        ticket=ticket,
        event_key=f"ticket.resolved.{ticket.pk}.{occurrence}",
    )


def _notify_property_fm(*, message: str, event_key_prefix: str, ticket=None) -> None:
    """Notify Təchizat operators (service_desk + supply.head) on new WO."""
    from apps.accounts.models import Role
    from apps.comms.services import notify_in_app
    from apps.rbac.models import UserPermission
    from django.contrib.auth import get_user_model

    User = get_user_model()
    role_ids = set(
        User.objects.filter(
            role__in=(Role.SERVICE_DESK,),
            is_active=True,
        ).values_list("pk", flat=True)[:40]
    )
    head_ids = set(
        UserPermission.objects.filter(
            permission__code="supply.head",
            user__is_active=True,
        ).values_list("user_id", flat=True)[:20]
    )
    for user in User.objects.filter(pk__in=role_ids | head_ids).order_by("pk"):
        notify_in_app(
            user=user,
            message=message,
            ticket=ticket,
            event_key=f"{event_key_prefix}.{user.pk}",
        )


def _work_order_assigned_notify(event: bus.DomainEvent) -> None:
    """Notify the WO assignee (technician) — not the whole FM list."""
    wo_id = event.payload.get("work_order_id")
    assignee_id = event.payload.get("assignee_id")
    if not wo_id or not assignee_id:
        return
    from apps.comms.services import notify_in_app
    from apps.maintenance.models import WorkOrder
    from django.contrib.auth import get_user_model

    User = get_user_model()
    wo = WorkOrder.objects.filter(pk=wo_id).first()
    user = User.objects.filter(pk=assignee_id, is_active=True).first()
    if not wo or not user:
        return
    notify_in_app(
        user=user,
        message=f"İş sifarişi təyin olundu: {wo.code}",
        ticket=wo.ticket if wo.ticket_id else None,
        event_key=f"wo.assigned.{wo.pk}.{assignee_id}",
    )


def _work_order_created_notify(event: bus.DomainEvent) -> None:
    code = (event.payload.get("code") or "").strip()
    wo_id = event.payload.get("work_order_id")
    ticket_id = event.payload.get("ticket_id")
    if not wo_id:
        return
    ticket = None
    if ticket_id:
        from apps.tickets.models import Ticket

        ticket = Ticket.objects.filter(pk=ticket_id).first()
    _notify_property_fm(
        message=f"Yeni iş sifarişi: {code or wo_id}",
        event_key_prefix=f"wo.created.{wo_id}",
        ticket=ticket,
    )


def _work_order_closed_notify(event: bus.DomainEvent) -> None:
    """After technical completion, Helpdesk owns ticket closure — not a second FM action."""
    code = (event.payload.get("code") or "").strip()
    wo_id = event.payload.get("work_order_id")
    if not wo_id:
        return
    from apps.comms.services import notify_in_app
    from apps.tickets.models import Ticket
    from apps.tickets.services import notify_department_users

    ticket_id = event.payload.get("ticket_id")
    ticket = Ticket.objects.select_related("assignee", "department").filter(pk=ticket_id).first() if ticket_id else None
    message = f"İş sifarişi texniki tamamlandı — ticket bağlanışı gözlənilir: {code or wo_id}"
    if ticket and ticket.assignee_id and ticket.assignee.is_active:
        notify_in_app(
            user=ticket.assignee,
            message=message,
            ticket=ticket,
            event_key=f"wo.closed.helpdesk.{wo_id}.{ticket.assignee_id}",
        )
        return
    if ticket is not None:
        notify_department_users(
            ticket,
            message,
            event_key=f"wo.closed.helpdesk.{wo_id}",
        )


def _active_role_users(*roles):
    """All active holders of the given roles, stable pk order (complete delivery).

    No artificial [:20] cap — duty-roster filtering is a separate CP policy
    decision; until then every eligible operator receives the alert.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return (
        User.objects.filter(role__in=roles, is_active=True)
        .order_by("pk")
        .iterator(chunk_size=50)
    )


def _visitor_checked_in_notify(event: bus.DomainEvent) -> None:
    """Actual admission only — notify the portal user who pre-registered the guest.

    Walk-in Reception actors already performed the check-in (no self-fan-out).
    Host is a ResidentEmployee without a User login link; Security/Reception
    broadcast on every admission remains a City Point policy decision.
    """
    visit_id = event.payload.get("visit_id")
    if not visit_id:
        return
    from apps.comms.services import notify_in_app
    from apps.reception.models import GuestVisit

    visit = (
        GuestVisit.objects.select_related("guest", "created_by_portal_user", "company")
        .filter(pk=visit_id)
        .first()
    )
    if visit is None:
        return
    portal_user = visit.created_by_portal_user
    if portal_user is None or not portal_user.is_active:
        return
    # Company scope: only if the creator still belongs to the visited company.
    company_id = visit.company_id
    user_company = getattr(portal_user, "resident_company_id", None)
    if company_id and user_company and user_company != company_id:
        from apps.accounts.models import PortalCompanyMembership

        if not PortalCompanyMembership.objects.filter(
            user=portal_user, company_id=company_id, is_active=True
        ).exists():
            return
    label = visit.guest.display_name if visit.guest_id else str(visit_id)
    notify_in_app(
        user=portal_user,
        message=f"Qonağınız qəbul edildi: {label}",
        event_key=f"visitor.checked_in.{visit_id}",
    )


def _visitor_return_pending_notify(event: bus.DomainEvent) -> None:
    """Security monitors exit; Reception must complete ID return.

    Audience (phase6 UAT A2, pending written CP confirmation): every active
    Security + Reception user. Ordered by pk for stable complete delivery —
    not a priority ranking. Display name only (no FIN/card).
    """
    visit_id = event.payload.get("visit_id")
    if not visit_id:
        return
    from apps.accounts.models import Role
    from apps.comms.services import notify_in_app
    from apps.reception.models import GuestVisit

    visit = GuestVisit.objects.select_related("guest").filter(pk=visit_id).first()
    label = visit.guest.display_name if visit and visit.guest_id else str(visit_id)
    for user in _active_role_users(Role.SECURITY):
        notify_in_app(
            user=user,
            message=f"Qonaq çıxışı — vəsiqə gözləyir: {label}",
            event_key=f"visitor.return_pending.{visit_id}.sec.{user.pk}",
        )
    for user in _active_role_users(Role.RECEPTION):
        notify_in_app(
            user=user,
            message=f"Vəsiqə qaytarılmalıdır: {label}",
            event_key=f"visitor.return_pending.{visit_id}.rec.{user.pk}",
        )


def _visitor_id_returned_notify(event: bus.DomainEvent) -> None:
    """Only after RETURN_PENDING completion — not every normal checkout."""
    if event.payload.get("completion") != "id_return":
        return
    visit_id = event.payload.get("visit_id")
    if not visit_id:
        return
    from apps.accounts.models import Role
    from apps.comms.services import notify_in_app
    from apps.reception.models import GuestVisit

    visit = GuestVisit.objects.select_related("guest").filter(pk=visit_id).first()
    label = visit.guest.display_name if visit and visit.guest_id else str(visit_id)
    for user in _active_role_users(Role.RECEPTION):
        notify_in_app(
            user=user,
            message=f"Vəsiqə qaytarıldı: {label}",
            event_key=f"visitor.id_returned.{visit_id}.{user.pk}",
        )


def _lease_activated_notify(event: bus.DomainEvent) -> None:
    """After ACTIVE transition (immediate or scheduled): Sales+Mgmt commercial
    awareness and Accountant deposit/billing follow-up.

    Same audience shape as expiry (commercial roles) plus Accountant for the
    deposit charge created on activate. Idempotent via event_key per lease.
    """
    lease_id = event.payload.get("lease_id")
    if not lease_id:
        return
    from apps.accounts.models import Role
    from apps.comms.services import notify_in_app
    from apps.leases.models import Lease

    lease = Lease.objects.filter(pk=lease_id).first()
    if lease is None:
        return
    code = lease.code or event.payload.get("code") or str(lease_id)
    start = lease.start_date.isoformat() if lease.start_date else ""
    msg = f"İcarə aktivləşdi: {code}" + (f" (başlanğıc: {start})" if start else "")
    key = f"lease.activated.{lease.pk}"
    for user in _active_role_users(
        Role.ADMIN, Role.MANAGEMENT, Role.SALES, Role.ACCOUNTANT
    ):
        notify_in_app(user=user, message=msg, event_key=f"{key}.{user.pk}")


def _approval_requested_notify(event: bus.DomainEvent) -> None:
    from apps.accounts.models import Role
    from apps.comms.services import notify_in_app
    from django.contrib.auth import get_user_model

    User = get_user_model()
    approval_id = event.payload.get("approval_id") or event.payload.get("request_id")
    code = event.payload.get("workflow_code") or "approval"
    for user in User.objects.filter(role__in={Role.ADMIN, Role.MANAGEMENT}, is_active=True)[:20]:
        notify_in_app(
            user=user,
            message=f"Təsdiq gözləyir: {code}",
            event_key=f"approval.requested.{approval_id or code}.{user.pk}",
        )


def _approval_decided_notify(event: bus.DomainEvent) -> None:
    """Notify original requester of approve/reject. Key includes decision identity for reopen."""
    approval_id = event.payload.get("approval_id") or event.payload.get("request_id")
    if not approval_id:
        return
    from apps.comms.services import notify_in_app
    from apps.workflows.models import ApprovalRequest, ApprovalStatus

    req = (
        ApprovalRequest.objects.select_related("requested_by")
        .filter(pk=approval_id)
        .first()
    )
    if req is None:
        return
    requester = req.requested_by
    if requester is None or not requester.is_active:
        return
    status = event.payload.get("status") or req.status
    decided_at = req.decided_at
    stamp = decided_at.isoformat() if decided_at else str(event.correlation_id or approval_id)
    if status == ApprovalStatus.APPROVED:
        decision_label = "təsdiqləndi"
    elif status == ApprovalStatus.REJECTED:
        decision_label = "rədd edildi"
    else:
        decision_label = status
    code = req.workflow_code or event.payload.get("workflow_code") or "approval"
    payload = req.payload or {}
    scope = (event.payload.get("decision_scope") or payload.get("decision_scope") or "").strip()
    amount = event.payload.get("amount") or payload.get("amount")
    currency = event.payload.get("currency") or payload.get("currency") or "AZN"
    if scope == "process_only":
        detail = "proses təsdiqi (məbləğ səlahiyyəti yoxdur)"
    elif scope == "process_and_amount" and amount:
        detail = f"maliyyə öhdəliyi {amount} {currency}"
    elif scope == "process_and_amount":
        detail = "qiymətli öhdəlik təsdiqi"
    else:
        detail = decision_label
    version_id = (
        payload.get("version_id")
        or payload.get("document_version_id")
        or event.payload.get("version_id")
        or event.payload.get("document_version_id")
    )
    if version_id:
        detail = f"{detail}; sənəd versiyası #{version_id}"
    notify_in_app(
        user=requester,
        message=f"Təsdiq qərarı ({code}): {detail} — {decision_label}",
        event_key=f"approval.decided.{approval_id}.{status}.{stamp}",
    )


def _po_received_notify(event: bus.DomainEvent) -> None:
    """Notify PR requester of a genuine receipt occurrence (keyed by operation)."""
    po_id = event.payload.get("po_id")
    op_key = (event.payload.get("operation_key") or "").strip()
    if not po_id:
        return
    from apps.comms.services import notify_in_app
    from apps.procurement.models import PurchaseOrder

    po = (
        PurchaseOrder.objects.select_related("pr", "pr__requested_by")
        .filter(pk=po_id)
        .first()
    )
    if po is None or not po.pr_id or not po.pr.requested_by_id:
        return
    user = po.pr.requested_by
    if not user.is_active:
        return
    status = event.payload.get("status") or po.status
    notify_in_app(
        user=user,
        message=f"PO qəbulu: {po.code} ({status})",
        event_key=f"po.received.notify.{po.pk}.op.{op_key or event.correlation_id}",
    )


def _purchase_approved_notify(event: bus.DomainEvent) -> None:
    """Process approval outcome — message must not imply spending authority."""
    pr_id = event.payload.get("pr_id")
    if not pr_id:
        return
    from apps.comms.services import notify_in_app
    from apps.procurement.models import PurchaseRequest

    pr = PurchaseRequest.objects.select_related("requested_by").filter(pk=pr_id).first()
    if pr is None or not pr.requested_by_id or not pr.requested_by.is_active:
        return
    notify_in_app(
        user=pr.requested_by,
        message=f"PR proses təsdiqi: {pr.code} (məbləğ səlahiyyəti ayrıca yoxlanır)",
        event_key=f"purchase.approved.{pr.pk}",
    )


_registered = False


def register_default_handlers() -> None:
    global _registered
    if _registered:
        return
    for name in (
        bus.TICKET_CREATED,
        bus.TICKET_ASSIGNED,
        bus.TICKET_RESOLVED,
        bus.VISITOR_CHECKED_IN,
        bus.VISITOR_CHECKED_OUT,
        bus.VISITOR_RETURN_PENDING,
        bus.LEASE_ACTIVATED,
        bus.LEASE_TERMINATED,
        bus.LEASE_EXPIRING,
        bus.LEASE_DRAFT_CREATED,
        bus.DEPOSIT_CHARGE_CREATED,
        bus.APPROVAL_REQUESTED,
        bus.APPROVAL_DECIDED,
        bus.WORK_ORDER_CREATED,
        bus.WORK_ORDER_ASSIGNED,
        bus.WORK_ORDER_CLOSED,
        bus.PURCHASE_APPROVED,
        bus.PO_RECEIVED,
    ):
        bus.subscribe(name, _audit_handler)
    bus.subscribe(bus.TICKET_CREATED, _ticket_created_notify)
    bus.subscribe(bus.TICKET_ASSIGNED, _ticket_assigned_notify)
    bus.subscribe(bus.TICKET_RESOLVED, _ticket_resolved_notify)
    bus.subscribe(bus.WORK_ORDER_CREATED, _work_order_created_notify)
    bus.subscribe(bus.WORK_ORDER_ASSIGNED, _work_order_assigned_notify)
    bus.subscribe(bus.WORK_ORDER_CLOSED, _work_order_closed_notify)
    bus.subscribe(bus.VISITOR_CHECKED_IN, _visitor_checked_in_notify)
    bus.subscribe(bus.VISITOR_RETURN_PENDING, _visitor_return_pending_notify)
    bus.subscribe(bus.VISITOR_CHECKED_OUT, _visitor_id_returned_notify)
    bus.subscribe(bus.LEASE_ACTIVATED, _lease_activated_notify)
    bus.subscribe(bus.APPROVAL_REQUESTED, _approval_requested_notify)
    bus.subscribe(bus.APPROVAL_DECIDED, _approval_decided_notify)
    bus.subscribe(bus.PO_RECEIVED, _po_received_notify)
    bus.subscribe(bus.PURCHASE_APPROVED, _purchase_approved_notify)
    _registered = True
