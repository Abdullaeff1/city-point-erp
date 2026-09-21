from django.contrib import admin

from apps.core.organization import Organization, OrgDepartment, OrgQueue, Team


class OrgDepartmentInline(admin.TabularInline):
    model = OrgDepartment
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")
    inlines = [OrgDepartmentInline]


class OrgQueueInline(admin.TabularInline):
    model = OrgQueue
    extra = 0


class TeamInline(admin.TabularInline):
    model = Team
    extra = 0


@admin.register(OrgDepartment)
class OrgDepartmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "organization", "is_active")
    list_filter = ("organization", "is_active")
    search_fields = ("code", "name")
    inlines = [OrgQueueInline, TeamInline]


@admin.register(OrgQueue)
class OrgQueueAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "department", "is_active")
    list_filter = ("department__organization",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "department", "is_active")
