from django.contrib import admin

from apps.comms.models import Announcement, Notification, NotificationDispatch


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "visibility", "company", "severity", "published_at")
    list_filter = ("visibility", "severity")
    filter_horizontal = ("target_users",)
    autocomplete_fields = ("company",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "message", "is_read", "created_at")


@admin.register(NotificationDispatch)
class NotificationDispatchAdmin(admin.ModelAdmin):
    list_display = ("channel", "template_code", "recipient", "status", "created_at", "sent_at")
    list_filter = ("channel", "status", "template_code")
    search_fields = ("recipient", "error_message")
    readonly_fields = ("created_at", "sent_at")
