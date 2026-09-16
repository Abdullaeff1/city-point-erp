from django.contrib import admin

from apps.crm.models import Lead, Offer, Opportunity


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("full_name", "company_name", "source", "status", "email", "phone", "created_at")
    list_filter = ("source", "status")
    search_fields = ("full_name", "email", "phone", "company_name", "external_id")


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ("title", "lead", "party", "status", "budget", "created_at")
    list_filter = ("status",)
    search_fields = ("title",)


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ("opportunity", "party", "space", "status", "rent_amount", "valid_until", "lease")
    list_filter = ("status",)
    search_fields = ("party__legal_name",)
