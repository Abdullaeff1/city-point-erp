from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0014_resident_company_profile"),
    ]

    operations = [
        migrations.AddField(
            model_name="residentcompany",
            name="legal_form",
            field=models.CharField(blank=True, max_length=64, verbose_name="Hüquqi forma"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="registry_extract_ref",
            field=models.CharField(
                blank=True,
                help_text="Reyestr çıxarışı nömrəsi / istinad (sənəd tipi: Reyestrdən çıxarış)",
                max_length=128,
                verbose_name="Reyestrdən çıxarış",
            ),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="website",
            field=models.URLField(blank=True, verbose_name="Veb-sayt"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="manager_position",
            field=models.CharField(blank=True, max_length=120, verbose_name="Rəhbər vəzifəsi"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="manager_email",
            field=models.EmailField(blank=True, max_length=254, verbose_name="Rəhbər email"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="bank_branch",
            field=models.CharField(blank=True, max_length=160, verbose_name="Bank filialı"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="bank_currency",
            field=models.CharField(
                blank=True, default="AZN", max_length=8, verbose_name="Hesab valyutası"
            ),
        ),
        migrations.AlterField(
            model_name="residentcompany",
            name="contact_email",
            field=models.EmailField(blank=True, max_length=254, verbose_name="Əsas email"),
        ),
        migrations.AlterField(
            model_name="residentcompany",
            name="manager_name",
            field=models.CharField(blank=True, max_length=160, verbose_name="Direktor / rəhbər"),
        ),
    ]
