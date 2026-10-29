import os

from django.conf import settings
from django.db import models


class AnnouncementSeverity(models.TextChoices):
    INFO = "info", "Info"
    IMPORTANT = "important", "Vacib"
    UPDATE = "update", "Yenilənmə"


class AnnouncementVisibility(models.TextChoices):
    BUILDING = "building", "Bina-ümumi"
    COMPANY = "company", "Şirkət"
    TARGETED = "targeted", "Hədəflənmiş"


class AnnouncementSource(models.TextChoices):
    MANUAL = "manual", "Əl ilə"
    OUTLOOK = "outlook", "Outlook"


class NotificationChannel(models.TextChoices):
    IN_APP = "in_app", "In-app"
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"


class Announcement(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField()
    severity = models.CharField(
        max_length=16, choices=AnnouncementSeverity.choices, default=AnnouncementSeverity.INFO
    )
    published_at = models.DateField()
    visibility = models.CharField(
        max_length=16,
        choices=AnnouncementVisibility.choices,
        default=AnnouncementVisibility.BUILDING,
    )
    company = models.ForeignKey(
        "residents.ResidentCompany",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="announcements",
        help_text="COMPANY / TARGETED üçün məcburi; BUILDING üçün boş",
    )
    target_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="targeted_announcements",
        help_text="TARGETED görünürlük üçün",
    )
    source = models.CharField(
        max_length=16,
        choices=AnnouncementSource.choices,
        default=AnnouncementSource.MANUAL,
        db_index=True,
    )
    external_message_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=True,
        help_text="Outlook/Graph internetMessageId (dedup)",
    )

    class Meta:
        ordering = ["-published_at"]

    def __str__(self):
        return self.title


class AnnouncementAttachment(models.Model):
    """PDF / file attachments shown in the announcement detail dialog."""

    announcement = models.ForeignKey(
        Announcement,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(upload_to="announcements/%Y/%m/")
    title = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self) -> str:
        if self.title.strip():
            return self.title.strip()
        return os.path.basename(self.file.name) if self.file else "—"


class Notification(models.Model):
    """In-app notification (Notification Engine channel=in_app)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True, on_delete=models.CASCADE, related_name="notifications"
    )
    message = models.CharField(max_length=255)
    event_key = models.CharField(
        max_length=160,
        blank=True,
        default="",
        db_default="",
        db_index=True,
        help_text="Dedup identifikatoru (mətn oxşarlığı deyil)",
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "event_key"],
                condition=~models.Q(event_key=""),
                name="uniq_notification_user_event_key",
            )
        ]


class NotificationDispatch(models.Model):
    """Outbox foundation for email/SMS (and audit of in-app sends)."""

    channel = models.CharField(max_length=16, choices=NotificationChannel.choices)
    status = models.CharField(max_length=16, default="pending")
    recipient = models.CharField(max_length=255, blank=True)
    template_code = models.CharField(max_length=64, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    notification = models.ForeignKey(
        Notification, null=True, blank=True, on_delete=models.SET_NULL, related_name="dispatches"
    )
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
