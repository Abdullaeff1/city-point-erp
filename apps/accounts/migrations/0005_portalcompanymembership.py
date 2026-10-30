# Generated manually for multi-company portal membership

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_user_ticket_department"),
        ("residents", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PortalCompanyMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True)),
                (
                    "is_primary",
                    models.BooleanField(
                        default=False,
                        help_text="Köhnə User.resident_company ilə uyğunluq; avtomatik login seçimi deyil",
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="portal_memberships",
                        to="residents.residentcompany",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_portal_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="portal_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Portal şirkət üzvlüyü",
                "verbose_name_plural": "Portal şirkət üzvlükləri",
                "ordering": ["-is_primary", "company__name"],
            },
        ),
        migrations.AddConstraint(
            model_name="portalcompanymembership",
            constraint=models.UniqueConstraint(
                fields=("user", "company"),
                name="uniq_portal_membership_user_company",
            ),
        ),
    ]
