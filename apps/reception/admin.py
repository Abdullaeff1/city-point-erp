from django.contrib import admin

from apps.reception.models import Guest, GuestVisit, VisitorAccess, VisitorType


@admin.register(VisitorType)
class VisitorTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")
    prepopulated_fields = {"code": ("name",)}
    search_fields = ("name", "code")


@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    list_display = ("display_name", "fin_code", "phone", "email", "is_active", "created_at")
    search_fields = ("first_name", "last_name", "full_name", "fin_code", "phone", "email")
    list_filter = ("is_active",)


class VisitorAccessInline(admin.StackedInline):
    model = VisitorAccess
    extra = 0
    readonly_fields = ("last_sync_at", "last_error", "created_at", "updated_at")


@admin.register(GuestVisit)
class GuestVisitAdmin(admin.ModelAdmin):
    list_display = (
        "guest",
        "company",
        "host",
        "visit_type",
        "status",
        "scheduled_for",
        "check_in_at",
        "check_out_at",
        "id_document_held",
        "invite_code",
    )
    list_filter = ("status", "visit_type", "scheduled_for", "id_document_held", "pre_registered")
    search_fields = (
        "guest__first_name",
        "guest__last_name",
        "guest__full_name",
        "guest__fin_code",
        "invite_code",
        "company__name",
    )
    raw_id_fields = ("guest", "company", "host", "space", "floor", "visit_type", "created_by", "created_by_portal_user")
    inlines = [VisitorAccessInline]
    readonly_fields = ("created_at", "updated_at")


@admin.register(VisitorAccess)
class VisitorAccessAdmin(admin.ModelAdmin):
    list_display = ("visit", "provider", "status", "sync_status", "external_id", "last_sync_at")
    list_filter = ("provider", "status", "sync_status")
    search_fields = ("external_id", "credential", "visit__invite_code")
