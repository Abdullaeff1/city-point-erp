from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

from apps.comms.models import Notification
from apps.tickets.models import SlaPolicy, Ticket, TicketMessage


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
    notify_company_users(ticket, f"Yeni cavab: {ticket.code}")
