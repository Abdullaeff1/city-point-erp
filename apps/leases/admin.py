from django.contrib import admin

from apps.leases.models import Lease, LeaseLine


class LeaseLineInline(admin.TabularInline):
    model = LeaseLine
    extra = 0


@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "party",
        "space",
        "status",
        "start_date",
        "end_date",
        "rent",
        "currency",
        "billing_active",
    )
    list_filter = ("status", "billing_active", "portal_eligible")
    search_fields = ("code", "party__legal_name", "space__code")
    inlines = [LeaseLineInline]


@admin.register(LeaseLine)
class LeaseLineAdmin(admin.ModelAdmin):
    list_display = ("lease", "space", "area_m2", "rent_share")
