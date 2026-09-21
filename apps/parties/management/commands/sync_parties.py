from django.core.management.base import BaseCommand

from apps.core.org_seed import seed_city_point_org
from apps.parties.services import PartyService
from apps.rbac.services import seed_rbac_catalog


class Command(BaseCommand):
    help = "Sync Party/Person from legacy Resident*, seed RBAC + Organization tree."

    def handle(self, *args, **options):
        sync = PartyService.sync_all_from_legacy()
        perms = seed_rbac_catalog()
        org = seed_city_point_org()
        self.stdout.write(
            self.style.SUCCESS(
                f"Synced parties={sync['parties']} people={sync['people']} "
                f"rbac_new={perms} org={org}"
            )
        )
