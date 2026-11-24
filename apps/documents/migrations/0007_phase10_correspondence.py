# Phase 10 correspondence / kargüzarlıq fields + dispatch.

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def seed_letter_types(apps, schema_editor):
    DocumentType = apps.get_model("documents", "DocumentType")
    defaults = {
        "incoming_letter": ("Daxil olan məktub", 3650, True, "confidential"),
        "outgoing_letter": ("Gedən məktub", 3650, True, "confidential"),
    }
    for code, (name, retention, requires_approval, sens) in defaults.items():
        DocumentType.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "retention_days": retention,
                "requires_approval": requires_approval,
                "default_sensitivity": sens,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("billing", "0001_scope1_12_domains"),
        ("documents", "0006_m9_sensitivity_outbox_retry"),
        ("maintenance", "0001_scope1_12_domains"),
        ("parties", "0001_scope0_foundation"),
        ("procurement", "0001_scope1_12_domains"),
        ("tickets", "0004_ticket_taxonomy_routing_lifecycle"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="correspondence_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("registered", "Qeydiyyatda"),
                    ("routed", "Yönləndirilib"),
                    ("in_progress", "İşlənir"),
                    ("pending_approval", "Təsdiq gözləyir"),
                    ("approved", "Təsdiqlənib"),
                    ("dispatched", "Göndərilib"),
                    ("closed", "Bağlı"),
                ],
                db_index=True,
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="direction",
            field=models.CharField(
                blank=True,
                choices=[("incoming", "Daxil olan"), ("outgoing", "Gedən")],
                db_index=True,
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="external_reference",
            field=models.CharField(blank=True, max_length=120, verbose_name="Göndərənin istinadı"),
        ),
        migrations.AddField(
            model_name="document",
            name="invoice",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="documents",
                to="billing.invoice",
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="party",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="documents",
                to="parties.party",
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="purchase_order",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="documents",
                to="procurement.purchaseorder",
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="purchase_request",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="documents",
                to="procurement.purchaserequest",
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="received_at",
            field=models.DateField(
                blank=True, db_index=True, null=True, verbose_name="Qəbul / daxilolma tarixi"
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="registry_number",
            field=models.CharField(
                blank=True, db_index=True, max_length=32, verbose_name="Daxili qeydiyyat №"
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="related_correspondence",
            field=models.ForeignKey(
                blank=True,
                help_text="Incoming↔outgoing reply pair",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="linked_correspondence",
                to="documents.document",
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="routed_department",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="routed_documents",
                to="tickets.ticketdepartment",
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="ticket",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="documents",
                to="tickets.ticket",
            ),
        ),
        migrations.AddField(
            model_name="document",
            name="work_order",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="documents",
                to="maintenance.workorder",
            ),
        ),
        migrations.CreateModel(
            name="CorrespondenceNumberSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "direction",
                    models.CharField(
                        choices=[("incoming", "Daxil olan"), ("outgoing", "Gedən")], max_length=16
                    ),
                ),
                ("year", models.PositiveIntegerField()),
                ("last_value", models.PositiveIntegerField(default=0)),
            ],
            options={"unique_together": {("direction", "year")}},
        ),
        migrations.CreateModel(
            name="DocumentDispatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("recipient", models.CharField(max_length=255)),
                (
                    "channel",
                    models.CharField(
                        default="manual",
                        help_text="manual|courier|hand|post — no external email required",
                        max_length=32,
                    ),
                ),
                ("dispatched_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("notes", models.CharField(blank=True, max_length=255)),
                ("operation_key", models.CharField(blank=True, db_index=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "dispatched_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="document_dispatches",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dispatches",
                        to="documents.document",
                    ),
                ),
                (
                    "version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dispatches",
                        to="documents.documentversion",
                    ),
                ),
            ],
            options={"ordering": ["-dispatched_at"]},
        ),
        migrations.AddConstraint(
            model_name="documentdispatch",
            constraint=models.UniqueConstraint(
                condition=~models.Q(operation_key=""),
                fields=("document", "operation_key"),
                name="uniq_document_dispatch_operation_key",
            ),
        ),
        migrations.RunPython(seed_letter_types, migrations.RunPython.noop),
    ]
