from django.contrib import admin

from apps.documents.models import Document, DocumentType, DocumentVersion


@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "requires_approval", "retention_days")
    prepopulated_fields = {"code": ("name",)}


class DocumentVersionInline(admin.TabularInline):
    model = DocumentVersion
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "document_type",
        "company",
        "visible_to_resident",
        "document_date",
        "published_at",
    )
    list_filter = ("document_type", "visible_to_resident", "file_type")
    search_fields = ("title", "company__name")
    raw_id_fields = ("company", "space", "lease", "parent_document")
    readonly_fields = ("created_at", "updated_at")
    inlines = [DocumentVersionInline]
