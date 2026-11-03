from django.db import migrations

EXTRA_TYPES = (
    ("power_of_attorney", "Etibarnamə"),
    ("bank_certificate", "Bank arayışı"),
    ("company_extract", "Reyestrdən çıxarış"),
)


def seed_extra_types(apps, schema_editor):
    DocumentType = apps.get_model("documents", "DocumentType")
    for code, name in EXTRA_TYPES:
        DocumentType.objects.get_or_create(code=code, defaults={"name": name})


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0004_document_private_profile"),
    ]

    operations = [
        migrations.RunPython(seed_extra_types, noop_reverse),
    ]
