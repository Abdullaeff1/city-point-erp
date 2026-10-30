from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from apps.accounts.invite import provision_portal_user, send_invite_email
from apps.residents.models import ResidentCompany


class Command(BaseCommand):
    help = (
        "Rezident Portal istifadəçisi yarat/yenilə və dəvət tokeni ver. "
        "Açıq self-signup yoxdur — yalnız Admin/ops bu əmri və ya Django Admin action istifadə edir. "
        "Birdən çox --company verilə bilər."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument(
            "--company",
            action="append",
            required=True,
            dest="companies",
            help="ResidentCompany slug (təkrarlana bilər)",
        )
        parser.add_argument("--first-name", default="")
        parser.add_argument("--last-name", default="")
        parser.add_argument(
            "--send-email",
            action="store_true",
            help="DEFAULT_FROM_EMAIL / EMAIL_* ilə dəvət maili göndər",
        )
        parser.add_argument(
            "--base-url",
            default="",
            help="Məs: https://portal.citypoint.az (email və çıxış linki üçün)",
        )

    def handle(self, *args, **options):
        companies = []
        for slug in options["companies"]:
            slug = slug.strip()
            company = ResidentCompany.objects.filter(slug=slug).first()
            if not company:
                raise CommandError(f"Company not found: {slug}")
            if company.is_internal:
                raise CommandError(
                    "Internal (City Point) şirkətinə portal user verməyin — ERP staff hesabı istifadə edin."
                )
            companies.append(company)

        user, raw = provision_portal_user(
            email=options["email"],
            companies=companies,
            first_name=options["first_name"],
            last_name=options["last_name"],
        )
        path = reverse("accounts:invite_accept", kwargs={"token": raw})
        base = (options.get("base_url") or "").rstrip("/")
        absolute = f"{base}{path}" if base else path

        slugs = ",".join(c.slug for c in companies)
        self.stdout.write(self.style.SUCCESS(f"User: {user.email} (id={user.pk}) companies={slugs}"))
        self.stdout.write(f"Invite path: {absolute}")

        if options["send_email"]:
            if not base:
                raise CommandError("--send-email üçün --base-url lazımdır (https://...)")
            send_invite_email(user=user, absolute_url=absolute)
            self.stdout.write(self.style.SUCCESS("Invite email sent."))
        else:
            self.stdout.write(
                "Email göndərilmədi. Linki əl ilə paylaşın və ya --send-email --base-url=... əlavə edin."
            )
