from django.contrib import admin

from apps.crm.models import Lead, LeadActivity, LeaseApplication, Offer, OfferVersion, Opportunity


class LeadActivityInline(admin.TabularInline):
    model = LeadActivity
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "company_name",
        "full_name",
        "source",
        "qualification",
        "pipeline_stage",
        "record_status",
        "created_at",
    )
    list_filter = ("source", "qualification", "pipeline_stage", "record_status")
    search_fields = ("full_name", "email", "phone", "company_name", "external_id")
    inlines = [LeadActivityInline]


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ("title", "lead", "party", "pipeline_stage", "status", "created_at")
    list_filter = ("status", "pipeline_stage")
    search_fields = ("title",)


class OfferVersionInline(admin.TabularInline):
    model = OfferVersion
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ("id", "opportunity", "party", "space", "status", "rent_amount", "sent_at", "lease")
    list_filter = ("status",)
    search_fields = ("party__legal_name",)
    inlines = [OfferVersionInline]


@admin.register(LeaseApplication)
class LeaseApplicationAdmin(admin.ModelAdmin):
    list_display = ("id", "person_name", "status", "offer", "space", "lease", "submitted_at")
    list_filter = ("status",)
    search_fields = ("person_name", "tax_id")
