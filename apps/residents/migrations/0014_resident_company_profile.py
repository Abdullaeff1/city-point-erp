# ResidentCompany legal/bank/contact/archive + audit fields; VOEN backfill from Party

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_voen_from_party(apps, schema_editor):
    ResidentCompany = apps.get_model("residents", "ResidentCompany")
    Party = apps.get_model("parties", "Party")
    for party in Party.objects.exclude(legacy_resident_company_id=None).exclude(tax_id=""):
        company = ResidentCompany.objects.filter(pk=party.legacy_resident_company_id).first()
        if company is None:
            continue
        if (company.voen or "").strip():
            continue
        tax = (party.tax_id or "").strip()
        if tax:
            company.voen = tax[:32]
            company.save(update_fields=["voen"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0013_access_event_result"),
        ("parties", "0001_scope0_foundation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="residentcompany",
            name="is_archived",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="archived_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="archived_resident_companies",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="voen",
            field=models.CharField(blank=True, max_length=32, verbose_name="VÖEN"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="charter_capital",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=14,
                null=True,
                verbose_name="Nizamnamə kapitalı (AZN)",
            ),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="justice_registration_no",
            field=models.CharField(blank=True, max_length=64, verbose_name="Ədliyyə qeydiyyat №"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="justice_registration_date",
            field=models.DateField(blank=True, null=True, verbose_name="Ədliyyə qeydiyyat tarixi"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="legal_address",
            field=models.CharField(blank=True, max_length=255, verbose_name="Hüquqi ünvan"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="actual_address",
            field=models.CharField(blank=True, max_length=255, verbose_name="Faktiki ünvan"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="billing_email",
            field=models.EmailField(blank=True, max_length=254, verbose_name="Faktura email"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="phone",
            field=models.CharField(blank=True, max_length=64, verbose_name="Telefon"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="manager_name",
            field=models.CharField(blank=True, max_length=160, verbose_name="Rəhbər şəxs"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="manager_phone",
            field=models.CharField(blank=True, max_length=64, verbose_name="Rəhbər telefon"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="contact_person_name",
            field=models.CharField(blank=True, max_length=160, verbose_name="Əlaqəli şəxs"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="contact_person_phone",
            field=models.CharField(blank=True, max_length=64, verbose_name="Əlaqə telefon"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="contact_person_email",
            field=models.EmailField(blank=True, max_length=254, verbose_name="Əlaqə email"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="bank_name",
            field=models.CharField(blank=True, max_length=160, verbose_name="Bank adı"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="bank_voen",
            field=models.CharField(blank=True, max_length=32, verbose_name="Bank VÖEN"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="bank_code",
            field=models.CharField(blank=True, max_length=32, verbose_name="Bank kodu"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="swift_bic",
            field=models.CharField(blank=True, max_length=32, verbose_name="SWIFT/BIC"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="iban",
            field=models.CharField(blank=True, max_length=64, verbose_name="IBAN"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="account_number",
            field=models.CharField(blank=True, max_length=64, verbose_name="Hesab nömrəsi"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="correspondent_account",
            field=models.CharField(blank=True, max_length=64, verbose_name="Müxbir hesab"),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_resident_companies",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="residentcompany",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="updated_resident_companies",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(backfill_voen_from_party, noop_reverse),
    ]
