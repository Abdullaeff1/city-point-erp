from django.contrib import admin

from apps.tickets.models import (
    RoutingRule,
    SlaPolicy,
    Ticket,
    TicketAttachment,
    TicketCategory,
    TicketDepartment,
    TicketMessage,
    TicketQueue,
    TicketRoutingEvent,
    TicketStatusEvent,
    TicketSubcategory,
)


class TicketSubcategoryInline(admin.TabularInline):
    model = TicketSubcategory
    extra = 0


@admin.register(TicketCategory)
class TicketCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "sort_order", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [TicketSubcategoryInline]


@admin.register(TicketSubcategory)
class TicketSubcategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "slug", "sort_order", "is_active")
    list_filter = ("category", "is_active")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(TicketDepartment)
class TicketDepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    prepopulated_fields = {"code": ("name",)}


@admin.register(TicketQueue)
class TicketQueueAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "department", "is_active")
    list_filter = ("department",)
    prepopulated_fields = {"code": ("name",)}


@admin.register(RoutingRule)
class RoutingRuleAdmin(admin.ModelAdmin):
    list_display = (
        "subcategory",
        "department",
        "queue",
        "default_priority",
        "wo_eligible",
        "crm_eligible",
        "is_active",
    )
    list_filter = ("department", "wo_eligible", "crm_eligible", "is_active")


@admin.register(SlaPolicy)
class SlaPolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "priority", "hours", "pause_on_waiting")


class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "ticket_type",
        "category",
        "subcategory",
        "company",
        "queue",
        "status",
        "priority",
        "assignee",
    )
    list_filter = ("status", "priority", "ticket_type", "department")
    search_fields = ("code", "description")
    inlines = [TicketMessageInline]


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "file", "uploaded_at")


@admin.register(TicketStatusEvent)
class TicketStatusEventAdmin(admin.ModelAdmin):
    list_display = ("ticket", "from_status", "to_status", "actor", "created_at")


@admin.register(TicketRoutingEvent)
class TicketRoutingEventAdmin(admin.ModelAdmin):
    list_display = ("ticket", "from_queue", "to_queue", "actor", "created_at")
