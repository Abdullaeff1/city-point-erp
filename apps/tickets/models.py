from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class TicketStatus(models.TextChoices):
    SENT = "sent", "Göndərildi"
    ACCEPTED = "accepted", "Qəbul edildi"
    IN_PROGRESS = "in_progress", "İcra olunur"
    RESOLVED = "resolved", "Həll edildi"


class TicketPriority(models.TextChoices):
    LOW = "low", "Aşağı"
    NORMAL = "normal", "Normal"
    HIGH = "high", "Yüksək"


OPEN_STATUSES = {TicketStatus.SENT, TicketStatus.ACCEPTED, TicketStatus.IN_PROGRESS}

STATUS_FLOW = {
    TicketStatus.SENT: TicketStatus.ACCEPTED,
    TicketStatus.ACCEPTED: TicketStatus.IN_PROGRESS,
    TicketStatus.IN_PROGRESS: TicketStatus.RESOLVED,
}


class TicketCategory(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)

    def __str__(self):
        return self.name


class SlaPolicy(models.Model):
    name = models.CharField(max_length=120)
    hours = models.PositiveIntegerField(default=24)
    priority = models.CharField(max_length=16, choices=TicketPriority.choices, unique=True)

    def __str__(self):
        return f"{self.get_priority_display()} / {self.hours}s"


class Ticket(models.Model):
    code = models.CharField(max_length=32, unique=True)
    category = models.ForeignKey(TicketCategory, on_delete=models.PROTECT, related_name="tickets")
    company = models.ForeignKey(
        "residents.ResidentCompany", on_delete=models.CASCADE, related_name="tickets"
    )
    space = models.ForeignKey(
        "property.Space", null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets"
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="requested_tickets"
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_tickets"
    )
    priority = models.CharField(max_length=16, choices=TicketPriority.choices, default=TicketPriority.NORMAL)
    status = models.CharField(max_length=24, choices=TicketStatus.choices, default=TicketStatus.SENT)
    description = models.TextField()
    sla_due_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES

    @property
    def sla_risk(self):
        if not self.sla_due_at or self.status == TicketStatus.RESOLVED:
            return False
        return timezone.now() >= self.sla_due_at - timedelta(hours=4)

    @property
    def next_status(self):
        return STATUS_FLOW.get(self.status)


class TicketMessage(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    author_label = models.CharField(max_length=120, blank=True)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class TicketAttachment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="tickets/%Y/%m/")
    uploaded_at = models.DateTimeField(auto_now_add=True)
