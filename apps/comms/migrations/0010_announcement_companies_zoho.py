from django.db import migrations, models


def copy_company_fk_to_m2m(apps, schema_editor):
    Announcement = apps.get_model("comms", "Announcement")
    through = Announcement.companies.through
    rows = []
    for ann in Announcement.objects.filter(company_id__isnull=False).iterator():
        rows.append(through(announcement_id=ann.pk, residentcompany_id=ann.company_id))
    if rows:
        through.objects.bulk_create(rows, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0017_parking_assignment_space"),
        ("comms", "0009_building_procedure"),
    ]

    operations = [
        migrations.AddField(
            model_name="announcement",
            name="companies",
            field=models.ManyToManyField(
                blank=True,
                help_text="COMPANY görünürlük: bir və ya bir neçə şirkət; BUILDING üçün boş",
                related_name="scoped_announcements",
                to="residents.residentcompany",
            ),
        ),
        migrations.AlterField(
            model_name="announcement",
            name="company",
            field=models.ForeignKey(
                blank=True,
                help_text="Legacy tək şirkət / TARGETED; COMPANY üçün companies M2M üstünlük təşkil edir",
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name="announcements",
                to="residents.residentcompany",
            ),
        ),
        migrations.AlterField(
            model_name="announcement",
            name="external_message_id",
            field=models.CharField(
                blank=True,
                help_text="Mail Message-ID / Graph id (dedup)",
                max_length=255,
                null=True,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="announcement",
            name="source",
            field=models.CharField(
                choices=[
                    ("manual", "Əl ilə"),
                    ("outlook", "Outlook (legacy)"),
                    ("zoho", "Zoho Mail"),
                ],
                db_index=True,
                default="manual",
                max_length=16,
            ),
        ),
        migrations.RunPython(copy_company_fk_to_m2m, migrations.RunPython.noop),
    ]
