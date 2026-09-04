from django.contrib import admin

from apps.reception.models import Guest, GuestVisit


@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    list_display = ("full_name",)


@admin.register(GuestVisit)
class GuestVisitAdmin(admin.ModelAdmin):
    list_display = ("guest", "company", "host", "status", "scheduled_for")
