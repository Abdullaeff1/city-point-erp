from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0007_rapid_card_swipe_alert"),
    ]

    operations = [
        migrations.AddField(
            model_name="accessevent",
            name="reader_id",
            field=models.PositiveIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="accessevent",
            name="reader_name",
            field=models.CharField(blank=True, max_length=160),
        ),
    ]
