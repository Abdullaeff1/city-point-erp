from django.contrib import admin

from apps.leases.models import DepositSettlement, Lease, LeaseAddon, LeaseLine


class LeaseLineInline(admin.TabularInline):
    model = LeaseLine
    extra = 0


class LeaseAddonInline(admin.TabularInline):
    model = LeaseAddon
    extra = 0


@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "party",
        "space",
        "status",
        "start_date",
        "rent_rate_per_m2",
        "rent",
        "billing_active",
    )
    list_filter = ("status", "billing_active", "portal_eligible", "parking_included_free")
    search_fields = ("code", "party__legal_name", "space__code")
    inlines = [LeaseLineInline, LeaseAddonInline]


@admin.register(LeaseLine)
class LeaseLineAdmin(admin.ModelAdmin):
    list_display = ("lease", "space", "area_m2", "rent_share")


@admin.register(LeaseAddon)
class LeaseAddonAdmin(admin.ModelAdmin):
    list_display = ("lease", "label", "rate_per_m2", "is_active")


@admin.register(DepositSettlement)
class DepositSettlementAdmin(admin.ModelAdmin):
    list_display = ("lease", "kind", "amount", "withhold_amount", "settled_at")
