from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.services import DomainError
from apps.tickets.access import (
    can_handoff_ticket,
    can_mutate_ticket,
    department_assignees,
)
from apps.tickets.models import (
    CLOSED_STATUSES,
    STATUS_FLOW,
    RoutingRule,
    SlaPolicy,
    Ticket,
    TicketAttachment,
    TicketDepartment,
    TicketMessage,
    TicketPriority,
    TicketQueue,
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


def _schedule_notify(fn):
    """Run notification after commit; never roll back the main transaction."""

    def _safe():
        try:
            fn()
        except Exception:
            pass

    transaction.on_commit(_safe)


def notify_company_users(ticket, message, *, event_key=""):
    from apps.accounts.models import User
    from apps.comms.services import notify_in_app

    users = list(User.objects.filter(resident_company=ticket.company, is_active=True))

    def _send():
        for u in users:
            key = f"{event_key}:u{u.pk}" if event_key else ""
            notify_in_app(user=u, message=message, ticket=ticket, event_key=key)

    _schedule_notify(_send)


def notify_department_users(ticket, message, *, event_key="", exclude_user_ids=None):
    from apps.accounts.models import User
    from apps.comms.services import notify_in_app

    if not ticket.department_id:
        return
    exclude_user_ids = set(exclude_user_ids or [])
    users = list(
        User.objects.filter(
            is_active=True,
            ticket_department_id=ticket.department_id,
        ).exclude(pk__in=exclude_user_ids)
    )

    def _send():
        for u in users:
            key = f"{event_key}:u{u.pk}" if event_key else ""
            notify_in_app(user=u, message=message, ticket=ticket, event_key=key)

    _schedule_notify(_send)


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
        ticket.priority = rule.default_priority
        fields.append("priority")
    ticket.save(update_fields=fields)

    event = TicketRoutingEvent.objects.create(
        ticket=ticket,
        from_department_id=prev_dept,
        to_department=rule.department,
        from_queue_id=prev_queue,
        to_queue=rule.queue,
        actor=actor,
        note=note,
    )
    apply_sla(ticket, force_policy=rule.sla_policy)
    notify_department_users(
        ticket,
        _("%(code)s şöbəyə yönləndirildi") % {"code": ticket.code},
        event_key=f"ticket.route.{ticket.pk}.{event.pk}",
        exclude_user_ids=[actor.pk] if actor else None,
    )
    return rule


def handoff_ticket(ticket, *, actor, department_id, queue_id=None, note=""):
    """Admin/Management only: move ticket to another department/queue."""
    if not can_handoff_ticket(actor, ticket):
        raise DomainError(_("Şöbələrarası yönləndirmə icazəsi yoxdur."))
    department = TicketDepartment.objects.filter(pk=department_id, is_active=True).first()
    if not department:
        raise DomainError(_("Şöbə tapılmadı."))
    queue = None
    if queue_id:
        queue = TicketQueue.objects.filter(pk=queue_id, is_active=True).first()
        if not queue:
            raise DomainError(_("Queue tapılmadı."))
        if queue.department_id != department.id:
            raise DomainError(_("Queue seçilmiş şöbəyə aid deyil."))
    else:
        queue = (
            TicketQueue.objects.filter(department=department, is_active=True)
            .order_by("name")
            .first()
        )

    prev_dept = ticket.department_id
    prev_queue = ticket.queue_id
    ticket.department = department
    ticket.queue = queue
    ticket.assignee = None
    ticket.save(update_fields=["department", "queue", "assignee", "updated_at"])

    event = TicketRoutingEvent.objects.create(
        ticket=ticket,
        from_department_id=prev_dept,
        to_department=department,
        from_queue_id=prev_queue,
        to_queue=queue,
        actor=actor,
        note=note or "handoff",
    )
    notify_department_users(
        ticket,
        _("%(code)s şöbənizə ötürüldü") % {"code": ticket.code},
        event_key=f"ticket.handoff.{ticket.pk}.{event.pk}",
        exclude_user_ids=[actor.pk] if actor else None,
    )
    return ticket


def add_message(ticket, user, body, label="", *, require_mutate=False):
    if require_mutate and not can_mutate_ticket(user, ticket):
        raise DomainError(_("Ticket redaktə icazəsi yoxdur."))
    msg = TicketMessage.objects.create(
        ticket=ticket,
        author=user,
        author_label=label or (user.get_full_name() or user.email),
        body=body,
    )
    notify_company_users(
        ticket,
        _("Yeni cavab: %(code)s") % {"code": ticket.code},
        event_key=f"ticket.message.{ticket.pk}.{msg.pk}",
    )
    return msg


def record_status_event(ticket, to_status, actor=None, from_status="", note=""):
    return TicketStatusEvent.objects.create(
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
    if actor is not None and not can_mutate_ticket(actor, ticket):
        raise DomainError(_("Ticket statusunu dəyişmək icazəsi yoxdur."))
    if not can_transition_to(ticket, new_status):
        raise DomainError(_("Bu status keçidinə icazə yoxdur."))
    if new_status == TicketStatus.WAITING and not (waiting_reason or note or "").strip():
        raise DomainError(_("Gözləmə səbəbi tələb olunur."))

    previous = ticket.status
    ticket.status = new_status
    update_fields = ["status", "updated_at"]

    if new_status == TicketStatus.WAITING:
        ticket.waiting_reason = (waiting_reason or note).strip()
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

    event = record_status_event(
        ticket, ticket.status, actor=actor, from_status=previous, note=note
    )
    msg = _("%(code)s statusu: %(status)s") % {
        "code": ticket.code,
        "status": ticket.get_status_display(),
    }
    ek = f"ticket.status.{ticket.pk}.{event.pk}"
    notify_company_users(ticket, msg, event_key=ek)
    notify_department_users(
        ticket,
        msg,
        event_key=ek,
        exclude_user_ids=[actor.pk] if actor else None,
    )
    _audit_status(ticket, actor, previous)
    return ticket


def advance_ticket_status(ticket, actor=None):
    nxt = ticket.next_status
    if not nxt:
        return ticket
    return set_ticket_status(ticket, nxt, actor=actor)


def citypoint_ticket_assignees():
    """Active City Point employees Service Desk can assign as the worker."""
    from apps.residents.models import ResidentEmployee

    return ResidentEmployee.objects.filter(
        company__slug="city-point",
        is_active=True,
    ).order_by("full_name")


def assign_ticket_employee(ticket, *, actor, employee_id=None):
    """Assign a City Point employee. Department user accounts are not the worker list."""
    if not can_mutate_ticket(actor, ticket):
        raise DomainError(_("Ticket təyinatı üçün icazə yoxdur."))
    employee = None
    if employee_id:
        employee = citypoint_ticket_assignees().filter(pk=employee_id).first()
        if employee is None:
            raise DomainError(_("Cavabdeh yalnız City Point əməkdaşı ola bilər."))
    ticket.assigned_employee = employee
    ticket.save(update_fields=["assigned_employee", "updated_at"])
    if employee and ticket.status == TicketStatus.SENT:
        set_ticket_status(ticket, TicketStatus.ASSIGNED, actor=actor, note="assigned")
    return ticket


def assign_ticket(ticket, *, actor, assignee_id=None):
    if not can_mutate_ticket(actor, ticket):
        raise DomainError(_("Ticket təyinatı üçün icazə yoxdur."))
    assignee = None
    if assignee_id:
        allowed = department_assignees(ticket).filter(pk=assignee_id).first()
        if not allowed:
            raise DomainError(_("Assignee yalnız ticket şöbəsinin əməkdaşı ola bilər."))
        assignee = allowed
    ticket.assignee = assignee
    ticket.save(update_fields=["assignee", "updated_at"])
    if assignee and ticket.status == TicketStatus.SENT:
        set_ticket_status(ticket, TicketStatus.ASSIGNED, actor=actor, note="assigned")
    elif assignee:
        notify_department_users(
            ticket,
            _("%(code)s təyin olundu: %(name)s")
            % {"code": ticket.code, "name": assignee.display_name},
            event_key=f"ticket.assign.{ticket.pk}.{assignee.pk}",
            exclude_user_ids=[actor.pk],
        )
    return ticket


def set_ticket_priority(ticket, *, actor, priority):
    if not can_mutate_ticket(actor, ticket):
        raise DomainError(_("Prioritet dəyişmək icazəsi yoxdur."))
    if priority not in dict(TicketPriority.choices):
        raise DomainError(_("Prioritet yanlışdır."))
    ticket.priority = priority
    ticket.save(update_fields=["priority", "updated_at"])
    apply_sla(ticket)
    return ticket


def set_enrichment_notes(ticket, *, actor, notes):
    if not can_mutate_ticket(actor, ticket):
        raise DomainError(_("Qeyd redaktəsi icazəsi yoxdur."))
    ticket.enrichment_notes = notes
    ticket.save(update_fields=["enrichment_notes", "updated_at"])
    return ticket


def attach_ticket_file(ticket, *, actor, upload):
    if not can_mutate_ticket(actor, ticket):
        raise DomainError(_("Fayl əlavə etmək icazəsi yoxdur."))
    if not upload:
        raise DomainError(_("Fayl seçilməyib."))
    return TicketAttachment.objects.create(ticket=ticket, file=upload)


def create_ticket_from_portal(
    *,
    company,
    requester,
    ticket_type,
    category,
    subcategory,
    description,
    space=None,
    priority_suggestion="",
    related_employee=None,
    author_label="Siz",
):
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
            related_employee=related_employee,
        )
        ticket.save()
        route_ticket(ticket, actor=requester, note="created", apply_default_priority=True)
        record_status_event(ticket, TicketStatus.SENT, actor=requester, note="created")
        add_message(ticket, requester, description, author_label, require_mutate=False)
        from apps.core import events as bus

        bus.emit(
            bus.TICKET_CREATED,
            payload={
                "ticket_id": ticket.pk,
                "code": ticket.code,
                "company_id": company.pk if company else None,
                "entity_model": "ticket",
            },
            actor=requester,
        )
        return ticket


def create_ticket_from_staff(
    *,
    actor,
    company,
    ticket_type,
    category,
    subcategory,
    description,
    space=None,
    priority="",
    assigned_employee=None,
):
    """Service Desk intake: same routing, plus an explicit priority and worker."""
    ticket = create_ticket_from_portal(
        company=company,
        requester=actor,
        ticket_type=ticket_type,
        category=category,
        subcategory=subcategory,
        description=description,
        space=space,
        author_label="Service Desk",
    )
    if priority:
        ticket.priority = priority
        ticket.save(update_fields=["priority", "updated_at"])
        apply_sla(ticket)
    if assigned_employee is not None:
        ticket.assigned_employee = assigned_employee
        ticket.save(update_fields=["assigned_employee", "updated_at"])
        if ticket.status == TicketStatus.SENT and can_transition_to(ticket, TicketStatus.ASSIGNED):
            if can_mutate_ticket(actor, ticket):
                set_ticket_status(ticket, TicketStatus.ASSIGNED, actor=actor, note="assigned")
            else:
                previous = ticket.status
                ticket.status = TicketStatus.ASSIGNED
                ticket.save(update_fields=["status", "updated_at"])
                record_status_event(
                    ticket,
                    TicketStatus.ASSIGNED,
                    actor=actor,
                    from_status=previous,
                    note="assigned",
                )
    return ticket


def create_work_order_from_ticket(ticket, *, actor, contractor_id=None):
    """Open a job for a contractor without moving the ticket to another department."""
    if not can_mutate_ticket(actor, ticket):
        raise DomainError(_("İş sifarişi yaratmaq icazəsi yoxdur."))
    from apps.maintenance.services import create_wo_from_ticket
    from apps.property.models import Contractor

    with transaction.atomic():
        wo = create_wo_from_ticket(ticket)
        title = ticket.code
        if ticket.subcategory_id:
            title = f"{ticket.code} — {ticket.subcategory.name}"
        wo.title = title[:200]
        update = ["title"]
        if contractor_id:
            contractor = Contractor.objects.filter(pk=contractor_id).first()
            if contractor is None:
                raise DomainError(_("Podratçı tapılmadı."))
            wo.contractor = contractor
            update.append("contractor")
        wo.save(update_fields=update)
    return wo


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
    if new_status == TicketStatus.ASSIGNED:
        return ticket.status == TicketStatus.SENT
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
