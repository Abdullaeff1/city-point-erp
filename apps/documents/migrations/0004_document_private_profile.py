import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.documents.storage


SEED_TYPES = (
    ("lease_contract", "İcarə müqaviləsi"),
    ("lease_amendment", "İcarə əlavəsi"),
    ("voen_certificate", "VÖEN şəhadətnaməsi"),
    ("charter", "Nizamnamə"),
    ("justice_registration", "Ədliyyə qeydiyyatı"),
    ("other", "Digər"),
)


def seed_document_types(apps, schema_editor):
    DocumentType = apps.get_model("documents", "DocumentType")
    for code, name in SEED_TYPES:
        DocumentType.objects.get_or_create(code=code, defaults={"name": name})


def backfill_document_date(apps, schema_editor):
    Document = apps.get_model("documents", "Document")
    for doc in Document.objects.filter(document_date__isnull=True).exclude(published_at=None):
        doc.document_date = doc.published_at
        doc.save(update_fields=["document_date"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0003_scope0_foundation"),
        ("leases", "0002_phases_3_13_foundations"),
        ("residents", "0014_resident_company_profile"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="document_date",
            field=models.DateField(blank=True, null=True, verbose_name="Sənəd tarixi"),
        ),
        migrations.AddField(
            model_name="document",
            name="visible_to_resident",
            field=models.BooleanField(default=False, verbose_name="Portala görünən"),
        ),
        migrations.AddField(
            model_name="document",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name="document",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name="document",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_documents",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="updated_documents",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="parent_document",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="amendments",
                to="documents.document",
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="lease",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="documents",
                to="leases.lease",
            ),
        ),
        migrations.AlterField(
            model_name="document",
            name="file",
            field=models.FileField(
                blank=True,
                storage=apps.documents.storage.PrivateDocumentStorage(),
                upload_to="documents/%Y/%m/",
            ),
        ),
        migrations.AlterField(
            model_name="documentversion",
            name="file",
            field=models.FileField(
                blank=True,
                storage=apps.documents.storage.PrivateDocumentStorage(),
                upload_to="documents/versions/%Y/%m/",
            ),
        ),
        migrations.RunPython(seed_document_types, noop_reverse),
        migrations.RunPython(backfill_document_date, noop_reverse),
    ]
