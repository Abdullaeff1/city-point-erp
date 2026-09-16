from django.contrib import admin

from apps.audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "object_repr", "actor", "source")
    list_filter = ("action", "source")
    search_fields = ("object_repr", "correlation_id", "action")
    readonly_fields = [f.name for f in AuditLog._meta.fields]
