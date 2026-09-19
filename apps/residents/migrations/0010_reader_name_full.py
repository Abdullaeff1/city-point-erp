from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0009_shaft_access_alert"),
    ]

    operations = [
        migrations.AlterField(
            model_name="accessevent",
            name="reader_name",
            field=models.CharField(
                blank=True,
                help_text="AxTrax tblReader.tDescReader (tam ad)",
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="shaftaccessalert",
            name="reader_name",
            field=models.CharField(
                blank=True,
                help_text="AxTrax oxuyucu adı (tam)",
                max_length=255,
            ),
        ),
    ]
