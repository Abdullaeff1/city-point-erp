# Generated manually for CRM / Satış module (A.10)

import django.db.models.deletion
import django.utils.timezone
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


def forwards_map_legacy_status(apps, schema_editor):
    Lead = apps.get_model("crm", "Lead")
    for lead in Lead.objects.all().iterator():
        status = lead.status
        if status == "qualified":
            lead.qualification = "potential"
            lead.record_status = "open"
            lead.pipeline_stage = "working"
        elif status == "disqualified":
            lead.qualification = "non_potential"
            lead.record_status = "closed"
            lead.pipeline_stage = "lost"
            lead.outcome = "invalid_request"
        elif status == "converted":
            lead.qualification = "potential"
            lead.record_status = "closed"
            lead.pipeline_stage = "won"
            lead.outcome = "cooperation_secured"
        else:
            lead.qualification = "unreviewed"
            lead.record_status = "open"
            lead.pipeline_stage = "working"
        lead.save(
            update_fields=[
                "qualification",
                "record_status",
                "pipeline_stage",
                "outcome",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("crm", "0002_scope1_12_domains"),
        ("leases", "0004_lease_commercial_a4"),
        ("parties", "0001_scope0_foundation"),
        ("property", "0002_alter_asset_id_alter_building_id_alter_contractor_id_and_more"),
        ("workflows", "0001_scope0_foundation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="lead",
            name="full_name",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="lead",
            name="source_note",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="lead",
            name="qualification",
            field=models.CharField(default="unreviewed", max_length=24),
        ),
        migrations.AddField(
            model_name="lead",
            name="qualification_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="record_status",
            field=models.CharField(default="open", max_length=16),
        ),
        migrations.AddField(
            model_name="lead",
            name="pipeline_stage",
            field=models.CharField(default="working", max_length=32),
        ),
        migrations.AddField(
            model_name="lead",
            name="outcome",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="lead",
            name="outcome_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="inquired_at",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="min_area_m2",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="max_area_m2",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="employee_count",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="employee_count_raw",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="lead",
            name="initial_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="contact_missing_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="owned_leads",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="lead",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_leads",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="lead",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.RunPython(forwards_map_legacy_status, migrations.RunPython.noop),
        migrations.CreateModel(
            name="LeadActivity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("activity_type", models.CharField(default="note", max_length=24)),
                ("occurred_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("body", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lead_activities",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "lead",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="activities",
                        to="crm.lead",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "lead activities",
                "ordering": ["-occurred_at", "-id"],
            },
        ),
        migrations.AddField(
            model_name="opportunity",
            name="pipeline_stage",
            field=models.CharField(default="working", max_length=32),
        ),
        migrations.AddField(
            model_name="opportunity",
            name="employee_count",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="opportunity",
            name="outcome",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="opportunity",
            name="outcome_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="opportunity",
            name="space",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="opportunities",
                to="property.space",
            ),
        ),
        migrations.AddField(
            model_name="opportunity",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="owned_opportunities",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="opportunity",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_opportunities",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="opportunity",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name="offer",
            name="sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="offer",
            name="sent_to",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="offer",
            name="sent_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sent_offers",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="offer",
            name="created_at",
            field=models.DateTimeField(default=django.utils.timezone.now, editable=False),
        ),
        migrations.AddField(
            model_name="offer",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.CreateModel(
            name="OfferVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version_number", models.PositiveIntegerField(default=1)),
                (
                    "rent_rate_per_m2",
                    models.DecimalField(decimal_places=2, default=Decimal("33.00"), max_digits=12),
                ),
                (
                    "vat_rate",
                    models.DecimalField(decimal_places=2, default=Decimal("18.00"), max_digits=5),
                ),
                ("area_m2", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                (
                    "discount_percent",
                    models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=5),
                ),
                ("discount_note", models.CharField(blank=True, max_length=255)),
                (
                    "package_text",
                    models.TextField(
                        blank=True,
                        default="Kommunal (internet xaric), təmizlik, təhlükəsizlik, reception, 7/24 xidmət daxildir.",
                    ),
                ),
                ("monthly_rent_net", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("monthly_vat", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("monthly_rent_gross", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("valid_until", models.DateField(blank=True, null=True)),
                ("pdf_file", models.FileField(blank=True, upload_to="crm/offers/%Y/%m/")),
                ("is_locked", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("notes", models.TextField(blank=True)),
                (
                    "approval_request",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="offer_versions",
                        to="workflows.approvalrequest",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_offer_versions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "offer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="versions",
                        to="crm.offer",
                    ),
                ),
            ],
            options={
                "ordering": ["-version_number", "-id"],
                "unique_together": {("offer", "version_number")},
            },
        ),
        migrations.AddField(
            model_name="offer",
            name="current_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="crm.offerversion",
            ),
        ),
        migrations.CreateModel(
            name="LeaseApplication",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(default="draft", max_length=40)),
                ("person_name", models.CharField(blank=True, max_length=200)),
                ("tax_id", models.CharField(blank=True, max_length=32)),
                ("legal_address", models.TextField(blank=True)),
                ("actual_address", models.TextField(blank=True)),
                ("floor_label", models.CharField(blank=True, max_length=64)),
                ("space_label", models.CharField(blank=True, max_length=128)),
                ("use_purpose", models.CharField(blank=True, max_length=255)),
                ("rent_rate_per_m2", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("monthly_rent_net", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("deposit_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("rent_free_note", models.CharField(blank=True, max_length=255)),
                ("cleaning_included", models.BooleanField(blank=True, null=True)),
                ("tea_service_included", models.BooleanField(blank=True, null=True)),
                ("lease_start", models.DateField(blank=True, null=True)),
                ("lease_end", models.DateField(blank=True, null=True)),
                ("bank_details", models.TextField(blank=True)),
                ("fit_out_notes", models.TextField(blank=True)),
                ("extra_notes", models.TextField(blank=True)),
                ("signer_title_name", models.CharField(blank=True, max_length=255)),
                ("is_legal_entity", models.BooleanField(default=True)),
                ("attachment_checklist", models.JSONField(blank=True, default=dict)),
                ("form_snapshot", models.JSONField(blank=True, default=dict)),
                ("sales_notes", models.TextField(blank=True)),
                ("accountant_notes", models.TextField(blank=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_lease_applications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "lease",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lease_applications",
                        to="leases.lease",
                    ),
                ),
                (
                    "offer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lease_applications",
                        to="crm.offer",
                    ),
                ),
                (
                    "offer_version",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lease_applications",
                        to="crm.offerversion",
                    ),
                ),
                (
                    "opportunity",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lease_applications",
                        to="crm.opportunity",
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_lease_applications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "space",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lease_applications",
                        to="property.space",
                    ),
                ),
                (
                    "submitted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="submitted_lease_applications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
