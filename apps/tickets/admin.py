from django.contrib import admin

from apps.tickets.models import SlaPolicy, Ticket, TicketAttachment, TicketCategory, TicketMessage


@admin.register(TicketCategory)
class TicketCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")


@admin.register(SlaPolicy)
class SlaPolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "priority", "hours")


class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("code", "category", "company", "status", "priority", "assignee")
    list_filter = ("status", "priority")
    inlines = [TicketMessageInline]


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "file", "uploaded_at")
