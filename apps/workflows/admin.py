"""Workflow Admin — ApprovalRequest is an audit trail; decisions go through ApprovalService."""

from django.contrib import admin

from apps.workflows.models import ApprovalRequest


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("workflow_code", "status", "requested_by", "created_at", "decided_at")
    list_filter = ("status", "workflow_code")
    search_fields = ("workflow_code", "comment")
    actions = None
    readonly_fields = (
        "workflow_code",
        "status",
        "requested_by",
        "decided_by",
        "decided_at",
        "comment",
        "entity_type",
        "entity_id",
        "payload",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_active and request.user.is_staff)
