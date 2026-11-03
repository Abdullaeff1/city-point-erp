from django.contrib import admin

from apps.comms.models import (
    Announcement,
    AnnouncementAttachment,
    BuildingProcedure,
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


@admin.register(BuildingProcedure)
class BuildingProcedureAdmin(admin.ModelAdmin):
    list_display = ("title", "is_published", "sort_order", "published_at", "updated_at")
    list_filter = ("is_published",)
    search_fields = ("title", "description")
    list_editable = ("is_published", "sort_order")
    readonly_fields = ("created_at", "updated_at", "created_by")
    fields = (
        "title",
        "description",
        "file",
        "sort_order",
        "is_published",
        "published_at",
        "created_by",
        "created_at",
        "updated_at",
    )

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        if obj.is_published and obj.published_at is None:
            from django.utils import timezone

            obj.published_at = timezone.localdate()
        super().save_model(request, obj, form, change)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "message", "is_read", "created_at")


@admin.register(NotificationDispatch)
class NotificationDispatchAdmin(admin.ModelAdmin):
    list_display = ("channel", "template_code", "recipient", "status", "created_at", "sent_at")
    list_filter = ("channel", "status", "template_code")
    search_fields = ("recipient", "error_message")
    readonly_fields = ("created_at", "sent_at")
