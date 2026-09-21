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
    pk = event.payload.get("ticket_id") or event.payload.get("visit_id") or event.payload.get("lease_id")
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
    """In-app notify assignee queue is future work; notify requester if staff created? skip for portal self."""
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
        bus.APPROVAL_REQUESTED,
        bus.APPROVAL_DECIDED,
    ):
        bus.subscribe(name, _audit_handler)
    bus.subscribe(bus.TICKET_CREATED, _ticket_created_notify)
    _registered = True
