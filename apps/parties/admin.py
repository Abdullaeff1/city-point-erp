from django.contrib import admin

from apps.parties.models import Party, PartyRole, Person


class PartyRoleInline(admin.TabularInline):
    model = PartyRole
    extra = 0


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ("legal_name", "party_type", "status", "tax_id", "legacy_resident_company")
    list_filter = ("party_type", "status")
    search_fields = ("legal_name", "brand_name", "tax_id", "contact_email")
    inlines = [PartyRoleInline]


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("full_name", "person_kind", "party", "email", "is_active")
    list_filter = ("person_kind", "is_active")
    search_fields = ("full_name", "email", "phone")
