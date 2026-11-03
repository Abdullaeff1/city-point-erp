from django.db import migrations, models


def backfill_company_snapshot(apps, schema_editor):
    AccessEvent = apps.get_model("residents", "AccessEvent")
    ResidentEmployee = apps.get_model("residents", "ResidentEmployee")
    emp_map = {
        e["id"]: (e["company_id"], e["company__name"] or "")
        for e in ResidentEmployee.objects.select_related("company").values(
            "id", "company_id", "company__name"
        )
    }
    batch = []
    for ev in AccessEvent.objects.filter(company_id__isnull=True).exclude(employee_id=None).iterator(
        chunk_size=2000
    ):
        info = emp_map.get(ev.employee_id)
        if not info:
            continue
        cid, cname = info
        ev.company_id = cid
        ev.company_name = (cname or "")[:160]
        batch.append(ev)
        if len(batch) >= 500:
            AccessEvent.objects.bulk_update(batch, ["company_id", "company_name"])
            batch = []
    if batch:
        AccessEvent.objects.bulk_update(batch, ["company_id", "company_name"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0015_resident_card_profile_gap"),
    ]

    operations = [
        migrations.AddField(
            model_name="accessevent",
            name="company_id",
            field=models.PositiveIntegerField(
                blank=True,
                db_index=True,
                help_text="Punch anında şirkət id (snapshot)",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="accessevent",
            name="company_name",
            field=models.CharField(
                blank=True,
                help_text="Punch anında şirkət adı (snapshot)",
                max_length=160,
            ),
        ),
        migrations.AlterField(
            model_name="accessevent",
            name="card_number",
            field=models.CharField(blank=True, db_index=True, max_length=32),
        ),
        migrations.RunPython(backfill_company_snapshot, noop_reverse),
    ]
