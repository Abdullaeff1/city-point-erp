"""In-process domain event bus — cross-module reactions without hard coupling.

Handlers must be fast and fail-soft (exceptions are logged, not raised to callers).
External systems stay behind adapters; this bus is internal only.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger(__name__)

Handler = Callable[["DomainEvent"], None]

# Well-known event names (Phase 2 minimum + room to grow)
TICKET_CREATED = "TicketCreated"
TICKET_ASSIGNED = "TicketAssigned"
TICKET_RESOLVED = "TicketResolved"
VISITOR_CHECKED_IN = "VisitorCheckedIn"
VISITOR_CHECKED_OUT = "VisitorCheckedOut"
LEASE_ACTIVATED = "LeaseActivated"
LEASE_TERMINATED = "LeaseTerminated"
WORK_ORDER_CLOSED = "WorkOrderClosed"
PURCHASE_APPROVED = "PurchaseApproved"
PO_RECEIVED = "POReceived"
INVOICE_GENERATED = "InvoiceGenerated"
PAYMENT_RECEIVED = "PaymentReceived"
APPROVAL_REQUESTED = "ApprovalRequested"
APPROVAL_DECIDED = "ApprovalDecided"


@dataclass
class DomainEvent:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    actor_id: int | None = None

    def __post_init__(self):
        if not self.correlation_id:
            self.correlation_id = uuid4().hex


_handlers: dict[str, list[Handler]] = defaultdict(list)


def subscribe(event_name: str, handler: Handler) -> None:
    if handler not in _handlers[event_name]:
        _handlers[event_name].append(handler)


def clear_handlers(event_name: str | None = None) -> None:
    """Test helper."""
    if event_name is None:
        _handlers.clear()
    else:
        _handlers.pop(event_name, None)
    # Allow register_default_handlers to run again after clear
    try:
        from apps.core import event_handlers

        event_handlers._registered = False
    except Exception:
        pass


def emit(event_name: str, *, payload: dict | None = None, actor=None, correlation_id: str = "") -> DomainEvent:
    event = DomainEvent(
        name=event_name,
        payload=payload or {},
        correlation_id=correlation_id,
        actor_id=getattr(actor, "pk", None) if actor is not None else None,
    )
    for handler in list(_handlers.get(event_name, [])):
        try:
            handler(event)
        except Exception:
            logger.exception("domain_event_handler_failed name=%s handler=%s", event_name, handler)
    return event
