from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.comms.models import Notification
from apps.tickets.models import SlaPolicy, Ticket, TicketMessage, TicketStatusEvent


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


def apply_sla(ticket):
    policy = SlaPolicy.objects.filter(priority=ticket.priority).first()
    hours = policy.hours if policy else 24
    ticket.sla_due_at = timezone.now() + timedelta(hours=hours)
    ticket.save(update_fields=["sla_due_at"])


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


def advance_ticket_status(ticket, actor=None):
    if not ticket.next_status:
        return ticket
    previous = ticket.status
    ticket.status = ticket.next_status
    ticket.save(update_fields=["status", "updated_at"])
    record_status_event(ticket, ticket.status, actor=actor, from_status=previous)
    notify_company_users(
        ticket,
        _("%(code)s statusu: %(status)s")
        % {"code": ticket.code, "status": ticket.get_status_display()},
    )
    return ticket
