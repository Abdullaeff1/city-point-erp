# Data migration: User.resident_company → PortalCompanyMembership

from django.db import migrations


def forwards(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    PortalCompanyMembership = apps.get_model("accounts", "PortalCompanyMembership")
    for user in User.objects.filter(resident_company_id__isnull=False).iterator():
        PortalCompanyMembership.objects.update_or_create(
            user_id=user.pk,
            company_id=user.resident_company_id,
            defaults={
                "is_active": True,
                "is_primary": True,
            },
        )


def backwards(apps, schema_editor):
    PortalCompanyMembership = apps.get_model("accounts", "PortalCompanyMembership")
    PortalCompanyMembership.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_portalcompanymembership"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
