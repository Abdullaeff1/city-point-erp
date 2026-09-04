# Generated for City Point V1

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="ResidentCompany",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=160)),
                ("slug", models.SlugField(unique=True)),
                ("status", models.CharField(choices=[("active", "Aktiv"), ("inactive", "Qeyri-aktiv")], default="active", max_length=16)),
                ("portal_active", models.BooleanField(default=True)),
                ("contact_email", models.EmailField(blank=True, max_length=254)),
                ("contract_start", models.DateField(blank=True, null=True)),
                ("contract_end", models.DateField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name="ResidentEmployee",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("full_name", models.CharField(max_length=160)),
                ("card_number", models.CharField(blank=True, max_length=32)),
                ("is_active", models.BooleanField(default=True)),
                ("company", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="employees", to="residents.residentcompany")),
            ],
        ),
        migrations.CreateModel(
            name="AccessEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("event_type", models.CharField(choices=[("in", "Giriş"), ("out", "Çıxış")], max_length=8)),
                ("occurred_at", models.DateTimeField()),
                ("employee", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="access_events", to="residents.residentemployee")),
            ],
            options={"ordering": ["-occurred_at"]},
        ),
    ]
