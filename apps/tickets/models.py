from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TicketType(models.TextChoices):
    INCIDENT = "incident", _("Hadisə")
    SERVICE_REQUEST = "service_request", _("Xidmət sorğusu")
    COMPLAINT = "complaint", _("Şikayət")
    COMMERCIAL = "commercial", _("Kommersiya sorğusu")


class TicketStatus(models.TextChoices):
    SENT = "sent", _("Yeni")
    ASSIGNED = "assigned", _("Təyin edildi")
    ACCEPTED = "accepted", _("Qəbul edildi")
    IN_PROGRESS = "in_progress", _("İcradadır")
    WAITING = "waiting", _("Gözləmədə")
    RESOLVED = "resolved", _("Həll edildi")
    CLOSED = "closed", _("Bağlandı")
    CANCELLED = "cancelled", _("Ləğv edildi")
    REOPENED = "reopened", _("Yenidən açıldı")


class TicketPriority(models.TextChoices):
    LOW = "low", _("Aşağı")
    NORMAL = "normal", _("Normal")
    HIGH = "high", _("Yüksək")
    CRITICAL = "critical", _("Kritik")


class WaitingReasonCode(models.TextChoices):
    RESIDENT_RESPONSE = "resident_response", _("Rezident cavabı")
    SPARE_PART = "spare_part", _("Ehtiyat hissə")
    CONTRACTOR = "contractor", _("Podratçı")
    APPROVAL = "approval", _("Təsdiq")
    OTHER = "other", _("Digər")


OPEN_STATUSES = {
    TicketStatus.SENT,
    TicketStatus.ASSIGNED,
    TicketStatus.ACCEPTED,
    TicketStatus.IN_PROGRESS,
    TicketStatus.WAITING,
    TicketStatus.REOPENED,
}

CLOSED_STATUSES = {
    TicketStatus.RESOLVED,
    TicketStatus.CLOSED,
    TicketStatus.CANCELLED,
}

# Default linear advance; waiting/cancel/reopen handled via explicit transitions.
STATUS_FLOW = {
    TicketStatus.SENT: TicketStatus.ACCEPTED,
    TicketStatus.ASSIGNED: TicketStatus.ACCEPTED,
    TicketStatus.ACCEPTED: TicketStatus.IN_PROGRESS,
    TicketStatus.REOPENED: TicketStatus.IN_PROGRESS,
    TicketStatus.IN_PROGRESS: TicketStatus.RESOLVED,
    TicketStatus.WAITING: TicketStatus.IN_PROGRESS,
    TicketStatus.RESOLVED: TicketStatus.CLOSED,
}


class TicketCategory(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "ticket categories"

    def __str__(self):
        return self.name


class TicketSubcategory(models.Model):
    category = models.ForeignKey(
        TicketCategory, on_delete=models.CASCADE, related_name="subcategories"
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField()
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    requires_description_min = models.PositiveSmallIntegerField(
        default=0,
        help_text=_("Other üçün minimum təsvir uzunluğu; 0 = yoxdur"),
    )

    class Meta:
        ordering = ["sort_order", "name"]
        unique_together = [("category", "slug")]
        verbose_name_plural = "ticket subcategories"

    def __str__(self):
        return f"{self.category.name} / {self.name}"


class TicketDepartment(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class TicketQueue(models.Model):
    department = models.ForeignKey(
        TicketDepartment, on_delete=models.CASCADE, related_name="queues"
    )
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.department.name} / {self.name}"


class SlaPolicy(models.Model):
    name = models.CharField(max_length=120)
    hours = models.PositiveIntegerField(default=24)
    priority = models.CharField(max_length=16, choices=TicketPriority.choices, unique=True)
    pause_on_waiting = models.BooleanField(
        default=True,
        help_text=_("Waiting statusunda SLA saatı dayansın"),
    )

    def __str__(self):
        return f"{self.get_priority_display()} / {self.hours}s"


class RoutingRule(models.Model):
    subcategory = models.OneToOneField(
        TicketSubcategory, on_delete=models.CASCADE, related_name="routing_rule"
    )
    department = models.ForeignKey(
        TicketDepartment, on_delete=models.PROTECT, related_name="routing_rules"
    )
    queue = models.ForeignKey(
        TicketQueue, on_delete=models.PROTECT, related_name="routing_rules"
    )
    default_priority = models.CharField(
        max_length=16, choices=TicketPriority.choices, default=TicketPriority.NORMAL
    )
    sla_policy = models.ForeignKey(
        SlaPolicy, null=True, blank=True, on_delete=models.SET_NULL, related_name="routing_rules"
    )
    wo_eligible = models.BooleanField(default=False)
    crm_eligible = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.subcategory} → {self.queue}"


class Ticket(models.Model):
    code = models.CharField(max_length=32, unique=True)
    ticket_type = models.CharField(
        max_length=32, choices=TicketType.choices, default=TicketType.INCIDENT
    )
    category = models.ForeignKey(TicketCategory, on_delete=models.PROTECT, related_name="tickets")
    subcategory = models.ForeignKey(
        TicketSubcategory,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    company = models.ForeignKey(
        "residents.ResidentCompany", on_delete=models.CASCADE, related_name="tickets"
    )
    space = models.ForeignKey(
        "property.Space", null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets"
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requested_tickets",
    )
    department = models.ForeignKey(
        TicketDepartment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
    )
    queue = models.ForeignKey(
        TicketQueue,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_tickets",
    )
    priority = models.CharField(
        max_length=16, choices=TicketPriority.choices, default=TicketPriority.NORMAL
    )
    resident_priority_suggestion = models.CharField(
        max_length=16, choices=TicketPriority.choices, blank=True
    )
    status = models.CharField(
        max_length=24, choices=TicketStatus.choices, default=TicketStatus.SENT
    )
    description = models.TextField()
    waiting_reason = models.CharField(max_length=255, blank=True)
    waiting_reason_code = models.CharField(
        max_length=32,
        choices=WaitingReasonCode.choices,
        blank=True,
        default="",
    )
    enrichment_notes = models.TextField(blank=True)
    resolution_note = models.TextField(blank=True)
    opportunity = models.ForeignKey(
        "crm.Opportunity",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_tickets",
    )
    related_employee = models.ForeignKey(
        "residents.ResidentEmployee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="card_order_tickets",
        help_text="Kart sifarişi / əməkdaş onboarding ticket-i",
    )
    sla_due_at = models.DateTimeField(null=True, blank=True)
    sla_paused_at = models.DateTimeField(null=True, blank=True)
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
    def wo_eligible(self):
        rule = getattr(self.subcategory, "routing_rule", None) if self.subcategory_id else None
        return bool(rule and rule.wo_eligible)

    @property
    def crm_eligible(self):
        rule = getattr(self.subcategory, "routing_rule", None) if self.subcategory_id else None
        if rule:
            return bool(rule.crm_eligible)
        return self.ticket_type == TicketType.COMMERCIAL

    @property
    def sla_breached(self):
        if not self.sla_due_at or self.status in CLOSED_STATUSES:
            return False
        if self.sla_paused_at:
            return False
        return timezone.now() >= self.sla_due_at

    @property
    def sla_risk(self):
        if not self.sla_due_at or self.status in CLOSED_STATUSES:
            return False
        if self.sla_paused_at:
            return False
        return timezone.now() >= self.sla_due_at - timedelta(hours=4)

    @property
    def sla_remaining(self):
        if not self.sla_due_at or self.status in CLOSED_STATUSES:
            return None
        if self.sla_paused_at:
            return self.sla_due_at - self.sla_paused_at
        return self.sla_due_at - timezone.now()

    @property
    def sla_remaining_label(self):
        remaining = self.sla_remaining
        if remaining is None:
            return "—"
        total = int(remaining.total_seconds())
        overdue = total < 0
        total = abs(total)
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)
        label = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"-{label}" if overdue else label

    @property
    def sla_percent_used(self):
        if not self.sla_due_at:
            return 0
        end = self.sla_paused_at or timezone.now()
        total = (self.sla_due_at - self.created_at).total_seconds()
        if total <= 0:
            return 100
        used = (end - self.created_at).total_seconds()
        return min(100, max(0, int(used / total * 100)))

    @property
    def next_status(self):
        return STATUS_FLOW.get(self.status)

    def get_next_status_display(self):
        nxt = self.next_status
        if not nxt:
            return ""
        return dict(TicketStatus.choices).get(nxt, nxt)


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


class TicketStatusEvent(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="status_events")
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24, choices=TicketStatus.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class TicketRoutingEvent(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="routing_events")
    from_department = models.ForeignKey(
        TicketDepartment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    to_department = models.ForeignKey(
        TicketDepartment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    from_queue = models.ForeignKey(
        TicketQueue, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    to_queue = models.ForeignKey(
        TicketQueue, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
