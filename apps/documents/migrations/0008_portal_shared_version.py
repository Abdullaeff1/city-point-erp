from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0007_phase10_correspondence"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="portal_shared_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="shared_as_portal_for",
                to="documents.documentversion",
                verbose_name="Portala paylaşılmış versiya",
            ),
        ),
    ]
