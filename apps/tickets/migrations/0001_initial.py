from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("property", "0001_initial"),
        ("residents", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="TicketCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=120)),
                ("slug", models.SlugField(unique=True)),
            ],
        ),
        migrations.CreateModel(
            name="SlaPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=120)),
                ("hours", models.PositiveIntegerField(default=24)),
                (
                    "priority",
                    models.CharField(
                        choices=[("low", "Aşağı"), ("normal", "Normal"), ("high", "Yüksək")],
                        max_length=16,
                        unique=True,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Ticket",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=32, unique=True)),
                (
                    "priority",
                    models.CharField(
                        choices=[("low", "Aşağı"), ("normal", "Normal"), ("high", "Yüksək")],
                        default="normal",
                        max_length=16,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("sent", "Göndərildi"),
                            ("accepted", "Qəbul edildi"),
                            ("in_progress", "İcra olunur"),
                            ("resolved", "Həll edildi"),
                        ],
                        default="sent",
                        max_length=24,
                    ),
                ),
                ("description", models.TextField()),
                ("sla_due_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "assignee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="assigned_tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("category", models.ForeignKey(on_delete=models.deletion.PROTECT, related_name="tickets", to="tickets.ticketcategory")),
                (
                    "company",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="tickets", to="residents.residentcompany"),
                ),
                (
                    "requester",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="requested_tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "space",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="tickets",
                        to="property.space",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="TicketMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("author_label", models.CharField(blank=True, max_length=120)),
                ("body", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("author", models.ForeignKey(null=True, on_delete=models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("ticket", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="messages", to="tickets.ticket")),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.CreateModel(
            name="TicketAttachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("file", models.FileField(upload_to="tickets/%Y/%m/")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("ticket", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="attachments", to="tickets.ticket")),
            ],
        ),
    ]
