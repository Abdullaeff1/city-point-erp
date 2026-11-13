from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.services import DomainError
from apps.tickets.access import (
    can_delete_ticket,
    can_handoff_ticket,
    can_mutate_ticket,
    department_assignees,
)
from apps.tickets.models import (
    CLOSED_STATUSES,
    DELETABLE_STATUSES,
    OPEN_STATUSES,
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
    WaitingReasonCode,
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
    """Apply SLA due date using business calendar (A.1).

    Prefer routing rule policy, else priority default.
    Hours are business hours: Mon–Sat 09:00–18:00, skip Novruz/state holidays.
    """
    from apps.tickets.business_calendar import add_business_hours

    policy = force_policy
    if policy is None and ticket.subcategory_id:
        rule = resolve_routing_rule(ticket.subcategory)
        if rule and rule.sla_policy_id:
            policy = rule.sla_policy
    if policy is None:
        policy = SlaPolicy.objects.filter(priority=ticket.priority).first()
    hours = policy.hours if policy else 8
    ticket.sla_due_at = add_business_hours(timezone.now(), hours)
    ticket.sla_paused_at = None
    ticket.save(update_fields=["sla_due_at", "sla_paused_at", "updated_at"])
    return policy


def pause_sla(ticket):
    if ticket.sla_due_at and not ticket.sla_paused_at:
        ticket.sla_paused_at = timezone.now()
        ticket.save(update_fields=["sla_paused_at", "updated_at"])


def resume_sla(ticket):
    """Resume SLA using remaining business hours at pause time (not wall-clock)."""
    if ticket.sla_paused_at and ticket.sla_due_at:
        from apps.tickets.business_calendar import add_business_hours, business_seconds_between

        remaining_sec = business_seconds_between(ticket.sla_paused_at, ticket.sla_due_at)
        if remaining_sec < 0:
            remaining_sec = 0
        ticket.sla_due_at = add_business_hours(timezone.now(), remaining_sec / 3600.0)
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


def _enqueue_ticket_email(user, *, message: str, template_code: str, ticket, event_key: str = ""):
    """Outbox email for ticket events (staff + residents with an address)."""
    recipient = (getattr(user, "email", "") or "").strip()
    if not recipient:
        return
    from apps.comms.services import enqueue_email

    enqueue_email(
        recipient=recipient,
        template_code=template_code,
        payload={
            "message": message,
            "ticket_code": ticket.code,
            "event_key": event_key,
            "ticket_id": ticket.pk,
        },
    )


def notify_company_users(ticket, message, *, event_key="", email_template="ticket.company"):
    from apps.accounts.models import User
    from apps.comms.services import notify_in_app

    users = list(User.objects.filter(resident_company=ticket.company, is_active=True))

    def _send():
        for u in users:
            key = f"{event_key}:u{u.pk}" if event_key else ""
            notify_in_app(user=u, message=message, ticket=ticket, event_key=key)
            _enqueue_ticket_email(
                u, message=message, template_code=email_template, ticket=ticket, event_key=key
            )

    _schedule_notify(_send)


def notify_department_users(
    ticket, message, *, event_key="", exclude_user_ids=None, email_template="ticket.department"
):
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
            _enqueue_ticket_email(
                u, message=message, template_code=email_template, ticket=ticket, event_key=key
            )

    _schedule_notify(_send)


def notify_management_users(ticket, message, *, event_key="", email_template="ticket.escalation"):
    """Admin / Management escalation recipients."""
    from apps.accounts.models import Role, User
    from apps.comms.services import notify_in_app

    users = list(
        User.objects.filter(is_active=True, role__in=(Role.ADMIN, Role.MANAGEMENT))
    )

    def _send():
        for u in users:
            key = f"{event_key}:u{u.pk}" if event_key else ""
            notify_in_app(user=u, message=message, ticket=ticket, event_key=key)
            _enqueue_ticket_email(
                u, message=message, template_code=email_template, ticket=ticket, event_key=key
            )

    _schedule_notify(_send)


def route_ticket(
    ticket,
    actor=None,
    note="routed",
    *,
    apply_default_priority=True,
):
    """Apply RoutingRule: department, queue, optional default priority + SLA.

    If subcategory has no active rule, fall back to category → default queue so
    tickets never sit with department=NULL (invisible to Security / Service Desk).
    """
    from apps.tickets.routing import fallback_department_and_queue

    rule = resolve_routing_rule(ticket.subcategory)
    department = rule.department if rule else None
    queue = rule.queue if rule else None
    if not department:
        department, queue = fallback_department_and_queue(ticket.category)
        if not department and ticket.subcategory_id and ticket.subcategory.category_id:
            department, queue = fallback_department_and_queue(ticket.subcategory.category)
    if not department:
        return None

    prev_dept = ticket.department_id
    prev_queue = ticket.queue_id
    ticket.department = department
    ticket.queue = queue
    fields = ["department", "queue", "updated_at"]
    if apply_default_priority and rule and ticket.priority != TicketPriority.CRITICAL:
        ticket.priority = rule.default_priority
        fields.append("priority")
    ticket.save(update_fields=fields)

    event = TicketRoutingEvent.objects.create(
        ticket=ticket,
        from_department_id=prev_dept,
        to_department=department,
        from_queue_id=prev_queue,
        to_queue=queue,
        actor=actor,
        note=note if rule else f"{note}:category-fallback",
    )
    apply_sla(ticket, force_policy=rule.sla_policy if rule else None)
    notify_department_users(
        ticket,
        _("%(code)s şöbəyə yönləndirildi") % {"code": ticket.code},
        event_key=f"ticket.route.{ticket.pk}.{event.pk}",
        exclude_user_ids=[actor.pk] if actor else None,
    )
    return rule


def handoff_ticket(ticket, *, actor, department_id, queue_id=None, note=""):
    """Move a misrouted ticket to another department. Current department or leadership."""
    if not can_handoff_ticket(actor, ticket):
        raise DomainError(_("Şöbələrarası yönləndirmə icazəsi yoxdur."))
    department = TicketDepartment.objects.filter(pk=department_id, is_active=True).first()
    if not department:
        raise DomainError(_("Şöbə tapılmadı."))
    if department.id == ticket.department_id:
        raise DomainError(_("Müraciət artıq bu şöbədədir."))
    queue = None
    if queue_id:
        queue = TicketQueue.objects.filter(pk=queue_id, is_active=True).first()
        if not queue:
            raise DomainError(_("Növbə tapılmadı."))
        if queue.department_id != department.id:
            raise DomainError(_("Növbə seçilmiş şöbəyə aid deyil."))
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
    ticket.assigned_employee = None
    ticket.save(
        update_fields=["department", "queue", "assignee", "assigned_employee", "updated_at"]
    )

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


def set_ticket_status(
    ticket,
    new_status,
    actor=None,
    note="",
    *,
    waiting_reason="",
    waiting_reason_code="",
):
    if new_status == ticket.status:
        return ticket
    if actor is not None and not can_mutate_ticket(actor, ticket):
        raise DomainError(_("Ticket statusunu dəyişmək icazəsi yoxdur."))
    if not can_transition_to(ticket, new_status):
        raise DomainError(_("Bu status keçidinə icazə yoxdur."))

    code = (waiting_reason_code or "").strip()
    reason_text = (waiting_reason or note or "").strip()
    if new_status == TicketStatus.WAITING:
        if code not in dict(WaitingReasonCode.choices):
            raise DomainError(_("Gözləmə səbəbi kodu tələb olunur."))
        if code == WaitingReasonCode.OTHER and not reason_text:
            raise DomainError(_("«Digər» üçün gözləmə mətni tələb olunur."))
        if not reason_text:
            reason_text = dict(WaitingReasonCode.choices).get(code, code)

    previous = ticket.status
    ticket.status = new_status
    update_fields = ["status", "updated_at"]

    if new_status == TicketStatus.WAITING:
        ticket.waiting_reason = reason_text
        ticket.waiting_reason_code = code
        update_fields.extend(["waiting_reason", "waiting_reason_code"])
        ticket.save(update_fields=update_fields)
        pause_sla(ticket)
    elif previous == TicketStatus.WAITING and new_status in {
        TicketStatus.IN_PROGRESS,
        TicketStatus.ACCEPTED,
        TicketStatus.REOPENED,
    }:
        ticket.waiting_reason = ""
        ticket.waiting_reason_code = ""
        update_fields.extend(["waiting_reason", "waiting_reason_code"])
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


def delete_ticket(ticket, *, actor):
    """Permanently remove a ticket that has not yet reached İcradadır."""
    if not can_delete_ticket(actor, ticket):
        if ticket.status not in DELETABLE_STATUSES:
            raise DomainError(_("İcradadır statusundan sonra ticket silinə bilməz."))
        raise DomainError(_("Ticket silmək icazəsi yoxdur."))
    code = ticket.code
    with transaction.atomic():
        for attachment in ticket.attachments.all():
            if attachment.file:
                attachment.file.delete(save=False)
        ticket.delete()
    return code


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
        route_ticket(
            ticket,
            actor=requester,
            note="created",
            apply_default_priority=True,
        )
        ticket.refresh_from_db(fields=["department_id", "queue_id", "priority"])
        if not ticket.department_id:
            raise DomainError(
                _(
                    "Müraciət şöbəyə yönləndirilə bilmədi. Kateqoriya/alt kateqoriya "
                    "və RoutingRule yoxlanmalıdır."
                )
            )
        record_status_event(ticket, TicketStatus.SENT, actor=requester, note="created")
        if (description or "").strip():
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
        author_label=company.name,
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


def create_opportunity_from_ticket(ticket, *, actor):
    """Commercial ticket → CRM Opportunity (manual; no silent auto-create)."""
    if not can_mutate_ticket(actor, ticket):
        raise DomainError(_("Opportunity yaratmaq icazəsi yoxdur."))
    if not ticket.crm_eligible:
        raise DomainError(_("Bu ticket CRM üçün uyğun deyil."))
    if ticket.opportunity_id:
        return ticket.opportunity

    from apps.audit.services import log_action
    from apps.crm.models import Opportunity, OpportunityStatus, PipelineStage
    from apps.parties.resolvers import party_for_company

    party = party_for_company(ticket.company, ensure=True) if ticket.company_id else None
    title = f"{ticket.code} — {ticket.company.name if ticket.company_id else 'Commercial'}"
    if ticket.subcategory_id:
        title = f"{ticket.code} — {ticket.subcategory.name}"
    opp = Opportunity.objects.create(
        title=title[:200],
        status=OpportunityStatus.OPEN,
        pipeline_stage=PipelineStage.WORKING,
        party=party,
        notes=(ticket.description or "")[:2000],
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
        owner=actor if getattr(actor, "is_authenticated", False) else None,
    )
    ticket.opportunity = opp
    ticket.save(update_fields=["opportunity", "updated_at"])
    log_action(
        actor=actor,
        action="crm.opportunity.from_ticket",
        entity=opp,
        message=f"{ticket.code} → opp#{opp.pk}",
        new_values={"ticket_id": ticket.pk, "ticket_code": ticket.code},
    )
    return opp


def desired_escalation_level(ticket) -> int:
    """0=none, 1=risk (≤2 business hours), 2=breach. Waiting pauses escalation."""
    if ticket.status in CLOSED_STATUSES or ticket.sla_paused_at or not ticket.sla_due_at:
        return 0
    if ticket.sla_breached:
        return 2
    if ticket.sla_risk:
        return 1
    return 0


def escalate_ticket_if_needed(ticket) -> int | None:
    """Raise escalation_level and notify dept + Admin/Management. Returns new level or None."""
    level = desired_escalation_level(ticket)
    if level <= (ticket.escalation_level or 0):
        return None
    ticket.escalation_level = level
    ticket.escalated_at = timezone.now()
    ticket.save(update_fields=["escalation_level", "escalated_at", "updated_at"])
    if level >= 2:
        msg = _("SLA pozuldu (eskalasiya): %(code)s") % {"code": ticket.code}
    else:
        msg = _("SLA riski: %(code)s") % {"code": ticket.code}
    ek = f"ticket.escalation.{ticket.pk}.{level}.{int(ticket.escalated_at.timestamp())}"
    notify_department_users(ticket, msg, event_key=ek, email_template="ticket.escalation")
    notify_management_users(ticket, msg, event_key=ek, email_template="ticket.escalation")
    return level


def scan_ticket_escalations(*, limit: int = 500) -> dict[str, int]:
    """Scan open tickets and escalate when SLA risk/breach. For poller / cron."""
    stats = {"checked": 0, "escalated": 0, "risk": 0, "breach": 0}
    qs = (
        Ticket.objects.filter(status__in=list(OPEN_STATUSES))
        .exclude(sla_due_at__isnull=True)
        .order_by("sla_due_at")[:limit]
    )
    for ticket in qs:
        stats["checked"] += 1
        level = escalate_ticket_if_needed(ticket)
        if level is None:
            continue
        stats["escalated"] += 1
        if level >= 2:
            stats["breach"] += 1
        else:
            stats["risk"] += 1
    return stats


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
