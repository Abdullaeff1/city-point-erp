from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("comms", "0006_notification_event_key_db_default"),
    ]

    operations = [
        migrations.CreateModel(
            name="AnnouncementAttachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to="announcements/%Y/%m/")),
                ("title", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "announcement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to="comms.announcement",
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
            },
        ),
    ]
