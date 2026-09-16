from django.core.management.base import BaseCommand

from apps.parties.services import PartyService
from apps.rbac.services import seed_rbac_catalog


class Command(BaseCommand):
    help = "Sync Party/Person from legacy ResidentCompany/Employee and seed RBAC catalog."

    def handle(self, *args, **options):
        sync = PartyService.sync_all_from_legacy()
        perms = seed_rbac_catalog()
        self.stdout.write(
            self.style.SUCCESS(
                f"Synced parties={sync['parties']} people={sync['people']} rbac_new={perms}"
            )
        )
