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
    list_display = ("title", "document_type", "file_type", "company", "space", "published_at")
    list_filter = ("document_type", "file_type")
    inlines = [DocumentVersionInline]
