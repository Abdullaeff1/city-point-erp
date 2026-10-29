from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("comms", "0007_announcement_attachment"),
    ]

    operations = [
        migrations.AddField(
            model_name="announcement",
            name="source",
            field=models.CharField(
                choices=[("manual", "Əl ilə"), ("outlook", "Outlook")],
                db_index=True,
                default="manual",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="announcement",
            name="external_message_id",
            field=models.CharField(
                blank=True,
                help_text="Outlook/Graph internetMessageId (dedup)",
                max_length=255,
                null=True,
                unique=True,
            ),
        ),
    ]
