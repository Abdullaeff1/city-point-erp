from django.conf import settings
from django.db import models


class AnnouncementSeverity(models.TextChoices):
    INFO = "info", "Info"
    IMPORTANT = "important", "Vacib"
    UPDATE = "update", "Yenilənmə"


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

    class Meta:
        ordering = ["-published_at"]

    def __str__(self):
        return self.title


class Notification(models.Model):
    """In-app notification (Notification Engine channel=in_app)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True, on_delete=models.CASCADE, related_name="notifications"
    )
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


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
