from django.conf import settings
from django.db import models


class AnnouncementSeverity(models.TextChoices):
    INFO = "info", "Info"
    IMPORTANT = "important", "Vacib"
    UPDATE = "update", "Yenilənmə"


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
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True, on_delete=models.CASCADE, related_name="notifications"
    )
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
