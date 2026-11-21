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
VISITOR_RETURN_PENDING = "VisitorReturnPending"
LEASE_ACTIVATED = "LeaseActivated"
LEASE_TERMINATED = "LeaseTerminated"
LEASE_EXPIRING = "LeaseExpiring"
LEASE_DRAFT_CREATED = "LeaseDraftCreated"
DEPOSIT_CHARGE_CREATED = "DepositChargeCreated"
WORK_ORDER_CREATED = "WorkOrderCreated"
WORK_ORDER_ASSIGNED = "WorkOrderAssigned"
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
# In-process emit dedupe: (event_name, event_key) → True. Cleared with clear_handlers().
_emitted_keys: set[str] = set()


def subscribe(event_name: str, handler: Handler) -> None:
    if handler not in _handlers[event_name]:
        _handlers[event_name].append(handler)


def clear_handlers(event_name: str | None = None) -> None:
    """Test helper."""
    if event_name is None:
        _handlers.clear()
        _emitted_keys.clear()
    else:
        _handlers.pop(event_name, None)
        prefix = f"{event_name}:"
        for key in list(_emitted_keys):
            if key.startswith(prefix):
                _emitted_keys.discard(key)
    # Allow register_default_handlers to run again after clear
    try:
        from apps.core import event_handlers

        event_handlers._registered = False
    except Exception:
        pass


def emit(
    event_name: str,
    *,
    payload: dict | None = None,
    actor=None,
    correlation_id: str = "",
    event_key: str = "",
) -> DomainEvent | None:
    """Emit a domain event. If ``event_key`` is set, skip duplicate (name, key) in this process."""
    if event_key:
        dedupe = f"{event_name}:{event_key}"
        if dedupe in _emitted_keys:
            logger.debug("domain_event_skipped_duplicate name=%s event_key=%s", event_name, event_key)
            return None
        _emitted_keys.add(dedupe)
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
