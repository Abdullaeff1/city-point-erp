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
    # Prefer concrete model instance lookup for common payloads
    pk = (
        event.payload.get("ticket_id")
        or event.payload.get("visit_id")
        or event.payload.get("lease_id")
        or event.payload.get("work_order_id")
        or event.payload.get("pr_id")
    )
    model_hint = event.payload.get("entity_model")
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
    notify_in_app(
        user=ticket.requester,
        message=f"Ticket həll olundu: {ticket.code}",
        ticket=ticket,
        event_key=f"ticket.resolved.{ticket.pk}",
    )


def _work_order_closed_notify(event: bus.DomainEvent) -> None:
    code = (event.payload.get("code") or "").strip()
    wo_id = event.payload.get("work_order_id")
    if not wo_id:
        return
    from apps.accounts.models import Role
    from apps.comms.services import notify_in_app
    from django.contrib.auth import get_user_model

    User = get_user_model()
    for user in User.objects.filter(role__in={Role.PROPERTY_FM, Role.ADMIN}, is_active=True)[:20]:
        notify_in_app(
            user=user,
            message=f"İş sifarişi bağlandı: {code or wo_id}",
            event_key=f"wo.closed.{wo_id}.{user.pk}",
        )


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
        bus.LEASE_ACTIVATED,
        bus.LEASE_TERMINATED,
        bus.LEASE_EXPIRING,
        bus.APPROVAL_REQUESTED,
        bus.APPROVAL_DECIDED,
        bus.WORK_ORDER_CLOSED,
        bus.PURCHASE_APPROVED,
        bus.PO_RECEIVED,
    ):
        bus.subscribe(name, _audit_handler)
    bus.subscribe(bus.TICKET_CREATED, _ticket_created_notify)
    bus.subscribe(bus.TICKET_ASSIGNED, _ticket_assigned_notify)
    bus.subscribe(bus.TICKET_RESOLVED, _ticket_resolved_notify)
    bus.subscribe(bus.WORK_ORDER_CLOSED, _work_order_closed_notify)
    bus.subscribe(bus.APPROVAL_REQUESTED, _approval_requested_notify)
    _registered = True
