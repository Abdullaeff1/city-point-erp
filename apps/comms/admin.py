from django.contrib import admin

from apps.comms.models import (
    Announcement,
    AnnouncementAttachment,
    Notification,
    NotificationDispatch,
)


class AnnouncementAttachmentInline(admin.TabularInline):
    model = AnnouncementAttachment
    extra = 0
    fields = ("title", "file")


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "source", "visibility", "company", "severity", "published_at")
    list_filter = ("source", "visibility", "severity")
    search_fields = ("title", "external_message_id")
    filter_horizontal = ("target_users",)
    autocomplete_fields = ("company",)
    readonly_fields = ("source", "external_message_id")
    inlines = [AnnouncementAttachmentInline]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "message", "is_read", "created_at")


@admin.register(NotificationDispatch)
class NotificationDispatchAdmin(admin.ModelAdmin):
    list_display = ("channel", "template_code", "recipient", "status", "created_at", "sent_at")
    list_filter = ("channel", "status", "template_code")
    search_fields = ("recipient", "error_message")
    readonly_fields = ("created_at", "sent_at")
