"""Create work orders for due preventive maintenance plans."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.maintenance.services import generate_work_orders_for_due_plans


class Command(BaseCommand):
    help = "Vaxtı çatmış MaintenancePlan-lardan Work Order yaradır."

    def add_arguments(self, parser):
        parser.add_argument(
            "--as-of",
            dest="as_of",
            default="",
            help="YYYY-MM-DD (default: today local)",
        )

    def handle(self, *args, **options):
        as_of = None
        raw = (options.get("as_of") or "").strip()
        if raw:
            as_of = timezone.datetime.strptime(raw, "%Y-%m-%d").date()
        stats = generate_work_orders_for_due_plans(as_of=as_of)
        self.stdout.write(
            self.style.SUCCESS(
                f"checked={stats['checked']} created={stats['created']} "
                f"advanced={stats['advanced']} skipped={stats['skipped']}"
            )
        )
