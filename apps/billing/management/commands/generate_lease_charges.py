from django.core.management.base import BaseCommand

from apps.leases.lease_ops import generate_monthly_lease_charges


class Command(BaseCommand):
    help = "Generate monthly rent/service charges for active billing leases."

    def handle(self, *args, **options):
        stats = generate_monthly_lease_charges()
        self.stdout.write(self.style.SUCCESS(str(stats)))
