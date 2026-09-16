from django.contrib import admin

from apps.workflows.models import ApprovalRequest


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("workflow_code", "status", "requested_by", "created_at", "decided_at")
    list_filter = ("status", "workflow_code")
