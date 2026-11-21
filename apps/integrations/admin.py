from django.contrib import admin

from apps.integrations.models import ExternalIdentity, SyncLog


@admin.register(ExternalIdentity)
class ExternalIdentityAdmin(admin.ModelAdmin):
    list_display = ("system", "external_id", "entity_type", "entity_id", "last_status", "last_sync_at")
    list_filter = ("system", "last_status")


@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "system", "operation", "status", "correlation_id", "error_message")
    list_filter = ("system", "status", "operation")
    search_fields = ("correlation_id", "error_message", "operation")
    readonly_fields = (
        "system",
        "operation",
        "status",
        "request_payload",
        "response_payload",
        "error_message",
        "correlation_id",
        "created_at",
        "updated_at",
    )
