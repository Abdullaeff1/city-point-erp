# Generated manually for TicketStatusEvent

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tickets", "0002_alter_slapolicy_id_alter_ticket_id_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="TicketStatusEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("from_status", models.CharField(blank=True, max_length=24)),
                (
                    "to_status",
                    models.CharField(
                        choices=[
                            ("sent", "Göndərildi"),
                            ("accepted", "Qəbul edildi"),
                            ("in_progress", "İcra olunur"),
                            ("resolved", "Həll edildi"),
                        ],
                        max_length=24,
                    ),
                ),
                ("note", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="status_events",
                        to="tickets.ticket",
                    ),
                ),
            ],
            options={"ordering": ["created_at"]},
        ),
    ]
