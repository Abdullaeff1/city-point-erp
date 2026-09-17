from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.comms.models import Notification
from apps.tickets.models import (
    CLOSED_STATUSES,
    STATUS_FLOW,
    RoutingRule,
    SlaPolicy,
    Ticket,
    TicketMessage,
    TicketPriority,
    TicketRoutingEvent,
    TicketStatus,
    TicketStatusEvent,
    TicketType,
)


def next_ticket_code():
    codes = Ticket.objects.filter(code__startswith="TK-").values_list("code", flat=True)
    numbers = []
    for code in codes:
        try:
            numbers.append(int(code.split("-")[1]))
        except (IndexError, ValueError):
            continue
    nxt = (max(numbers) + 1) if numbers else 1001
    return f"TK-{nxt}"


def resolve_routing_rule(subcategory):
    if not subcategory:
        return None
    try:
        rule = subcategory.routing_rule
    except RoutingRule.DoesNotExist:
        return None
    if not rule.is_active:
        return None
    return rule


def apply_sla(ticket, *, force_policy=None):
    """Apply SLA due date. Prefer routing rule policy, else priority default."""
    policy = force_policy
    if policy is None and ticket.subcategory_id:
        rule = resolve_routing_rule(ticket.subcategory)
        if rule and rule.sla_policy_id:
            policy = rule.sla_policy
    if policy is None:
        policy = SlaPolicy.objects.filter(priority=ticket.priority).first()
    hours = policy.hours if policy else 24
    ticket.sla_due_at = timezone.now() + timedelta(hours=hours)
    ticket.sla_paused_at = None
    ticket.save(update_fields=["sla_due_at", "sla_paused_at", "updated_at"])
    return policy


def pause_sla(ticket):
    if ticket.sla_due_at and not ticket.sla_paused_at:
        ticket.sla_paused_at = timezone.now()
        ticket.save(update_fields=["sla_paused_at", "updated_at"])


def resume_sla(ticket):
    if ticket.sla_paused_at and ticket.sla_due_at:
        paused_for = timezone.now() - ticket.sla_paused_at
        ticket.sla_due_at = ticket.sla_due_at + paused_for
        ticket.sla_paused_at = None
        ticket.save(update_fields=["sla_due_at", "sla_paused_at", "updated_at"])


def route_ticket(ticket, actor=None, note="routed", *, apply_default_priority=True):
    """Apply RoutingRule: department, queue, optional default priority + SLA."""
    rule = resolve_routing_rule(ticket.subcategory)
    if not rule:
        return None

    prev_dept = ticket.department_id
    prev_queue = ticket.queue_id
    ticket.department = rule.department
    ticket.queue = rule.queue
    fields = ["department", "queue", "updated_at"]
    if apply_default_priority and ticket.priority != TicketPriority.CRITICAL:
        # Keep staff critical; otherwise use rule default (resident suggestion ignored for final).
        ticket.priority = rule.default_priority
        fields.append("priority")
    ticket.save(update_fields=fields)

    TicketRoutingEvent.objects.create(
        ticket=ticket,
        from_department_id=prev_dept,
        to_department=rule.department,
        from_queue_id=prev_queue,
        to_queue=rule.queue,
        actor=actor,
        note=note,
    )
    apply_sla(ticket, force_policy=rule.sla_policy)
    return rule


def notify_company_users(ticket, message):
    from apps.accounts.models import User

    users = User.objects.filter(resident_company=ticket.company)
    Notification.objects.bulk_create(
        [Notification(user=u, ticket=ticket, message=message) for u in users]
    )


def add_message(ticket, user, body, label=""):
    TicketMessage.objects.create(
        ticket=ticket,
        author=user,
        author_label=label or (user.get_full_name() or user.email),
        body=body,
    )
    notify_company_users(ticket, _("Yeni cavab: %(code)s") % {"code": ticket.code})


def record_status_event(ticket, to_status, actor=None, from_status="", note=""):
    TicketStatusEvent.objects.create(
        ticket=ticket,
        from_status=from_status or "",
        to_status=to_status,
        actor=actor,
        note=note,
    )


def _audit_status(ticket, actor, previous):
    try:
        from apps.audit.services import log_action

        log_action(
            action="ticket.status_change",
            actor=actor,
            entity=ticket,
            old_values={"status": previous},
            new_values={"status": ticket.status},
            source="tickets",
        )
    except Exception:
        pass


def set_ticket_status(ticket, new_status, actor=None, note="", *, waiting_reason=""):
    if new_status == ticket.status:
        return ticket
    previous = ticket.status
    ticket.status = new_status
    update_fields = ["status", "updated_at"]

    if new_status == TicketStatus.WAITING:
        ticket.waiting_reason = waiting_reason or note or ticket.waiting_reason
        update_fields.append("waiting_reason")
        ticket.save(update_fields=update_fields)
        pause_sla(ticket)
    elif previous == TicketStatus.WAITING and new_status in {
        TicketStatus.IN_PROGRESS,
        TicketStatus.ACCEPTED,
        TicketStatus.REOPENED,
    }:
        ticket.waiting_reason = ""
        update_fields.append("waiting_reason")
        ticket.save(update_fields=update_fields)
        resume_sla(ticket)
    else:
        ticket.save(update_fields=update_fields)

    if new_status == TicketStatus.RESOLVED and note:
        ticket.resolution_note = note
        ticket.save(update_fields=["resolution_note", "updated_at"])

    record_status_event(ticket, ticket.status, actor=actor, from_status=previous, note=note)
    notify_company_users(
        ticket,
        _("%(code)s statusu: %(status)s")
        % {"code": ticket.code, "status": ticket.get_status_display()},
    )
    _audit_status(ticket, actor, previous)
    return ticket


def advance_ticket_status(ticket, actor=None):
    nxt = ticket.next_status
    if not nxt:
        return ticket
    return set_ticket_status(ticket, nxt, actor=actor)


def create_ticket_from_portal(*, company, requester, ticket_type, category, subcategory, description, space=None, priority_suggestion=""):
    """Thin intake: route via subcategory rule, apply SLA, record created event."""
    with transaction.atomic():
        ticket = Ticket(
            code=next_ticket_code(),
            ticket_type=ticket_type or TicketType.INCIDENT,
            category=category,
            subcategory=subcategory,
            company=company,
            requester=requester,
            space=space,
            description=description,
            status=TicketStatus.SENT,
            resident_priority_suggestion=priority_suggestion or "",
            priority=TicketPriority.NORMAL,
        )
        ticket.save()
        route_ticket(ticket, actor=requester, note="created", apply_default_priority=True)
        record_status_event(ticket, TicketStatus.SENT, actor=requester, note="created")
        add_message(ticket, requester, description, "Siz")
        return ticket


def create_crm_opportunity_from_ticket(ticket, actor=None):
    """Manual CRM handoff for commercial-eligible tickets."""
    if ticket.opportunity_id:
        return ticket.opportunity
    from apps.crm.models import Opportunity, OpportunityStatus

    party = None
    company = ticket.company
    if hasattr(company, "party_id") and company.party_id:
        party = company.party
    else:
        try:
            from apps.parties.models import Party

            party = Party.objects.filter(name=company.name).first()
        except Exception:
            party = None

    label = ticket.subcategory.name if ticket.subcategory_id else ticket.category.name
    title = f"{ticket.code}: {label}"
    opp = Opportunity.objects.create(
        title=title[:200],
        status=OpportunityStatus.OPEN,
        party=party,
        notes=ticket.description,
    )
    ticket.opportunity = opp
    ticket.save(update_fields=["opportunity", "updated_at"])
    record_status_event(
        ticket,
        ticket.status,
        actor=actor,
        from_status=ticket.status,
        note=f"CRM Opportunity #{opp.pk}",
    )
    return opp


def allowed_staff_priorities():
    return TicketPriority.choices


def allowed_resident_priorities():
    return [
        (TicketPriority.LOW, _("Aşağı")),
        (TicketPriority.NORMAL, _("Normal")),
        (TicketPriority.HIGH, _("Yüksək")),
    ]


def can_transition_to(ticket, new_status):
    if new_status == ticket.status:
        return False
    if new_status == TicketStatus.WAITING:
        return ticket.status in {
            TicketStatus.IN_PROGRESS,
            TicketStatus.ACCEPTED,
            TicketStatus.ASSIGNED,
        }
    if new_status == TicketStatus.CANCELLED:
        return ticket.status not in CLOSED_STATUSES
    if new_status == TicketStatus.REOPENED:
        return ticket.status in {TicketStatus.RESOLVED, TicketStatus.CLOSED}
    if new_status == TicketStatus.CLOSED:
        return ticket.status == TicketStatus.RESOLVED
    return STATUS_FLOW.get(ticket.status) == new_status
