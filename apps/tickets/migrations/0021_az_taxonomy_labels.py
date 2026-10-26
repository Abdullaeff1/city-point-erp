from django.db import migrations


def az_labels(apps, schema_editor):
    Department = apps.get_model("tickets", "TicketDepartment")
    Queue = apps.get_model("tickets", "TicketQueue")
    Category = apps.get_model("tickets", "TicketCategory")
    Subcategory = apps.get_model("tickets", "TicketSubcategory")

    departments = {
        "property": "Əmlak / İcarə",
    }
    queues = {
        "hvac": "HVAC növbəsi",
        "electric": "Elektrik növbəsi",
        "plumbing": "Santexnika növbəsi",
        "lift": "Lift növbəsi",
        "technical": "Texniki növbə",
        "cleaning": "Təmizlik növbəsi",
        "security": "Təhlükəsizlik növbəsi",
        "parking": "Parkinq növbəsi",
        "leasing": "İcarə növbəsi",
        "contract": "Müqavilə növbəsi",
        "ar": "AR növbəsi",
        "docs": "Sənəd növbəsi",
        "general": "Ümumi növbə",
    }
    categories = {
        "technical": "Texniki",
        "parking": "Parkinq",
        "commercial-space": "Kommersiya / Sahə",
        "lease": "İcarə / Müqavilə",
        "billing": "Hesablaşma",
        "administration": "İnzibati / Sənədlər",
        "other": "Digər",
        "hvac": "HVAC (köhnə)",
        "electric": "Elektrik (köhnə)",
        "access": "Keçid (köhnə)",
    }
    subcategories = {
        ("cleaning", "common-area"): "Ümumi sahə",
        ("parking", "parking-issue"): "Parkinq problemi",
        ("parking", "parking-change"): "Mövcud parkinq dəyişikliyi",
        ("parking", "parking-extra"): "Əlavə parkinq tələbi",
        ("lease", "amendment"): "Dəyişiklik",
        ("lease", "renewal"): "Uzadılma",
        ("lease", "termination"): "Xitam",
        ("billing", "invoice"): "Faktura",
        ("billing", "service-charge"): "Xidmət haqqı",
    }

    for code, name in departments.items():
        Department.objects.filter(code=code).update(name=name)
    for code, name in queues.items():
        Queue.objects.filter(code=code).update(name=name)
    for slug, name in categories.items():
        Category.objects.filter(slug=slug).update(name=name)
    for (category_slug, slug), name in subcategories.items():
        Subcategory.objects.filter(category__slug=category_slug, slug=slug).update(name=name)


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0020_hide_access_fault"),
    ]

    operations = [
        migrations.RunPython(az_labels, migrations.RunPython.noop),
    ]
