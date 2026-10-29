from django.db import migrations, models


def classify_existing(apps, schema_editor):
    BuildingAsset = apps.get_model("property", "BuildingAsset")
    BuildingAsset.objects.filter(category="furniture").update(kind="inventory")
    BuildingAsset.objects.exclude(category="furniture").update(kind="equipment")


class Migration(migrations.Migration):

    dependencies = [
        ("property", "0005_building_asset"),
    ]

    operations = [
        migrations.AddField(
            model_name="buildingasset",
            name="kind",
            field=models.CharField(
                choices=[("equipment", "Avadanlıq"), ("inventory", "İnventar")],
                db_index=True,
                default="equipment",
                max_length=16,
            ),
        ),
        migrations.RunPython(classify_existing, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name="buildingasset",
            options={"ordering": ["kind", "category", "name"]},
        ),
    ]
