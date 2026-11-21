"""List approved procurement.pr rows whose amount lacks verified monetary provenance."""

from django.core.management.base import BaseCommand

from apps.procurement.services import ProcurementService


class Command(BaseCommand):
    help = (
        "Report historical procurement.pr approvals that carry an amount without "
        "decision_scope=process_and_amount + verified amount_basis. These must not "
        "authorize new PO spending ceilings."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="Max rows to print (default 500).",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        rows = list(ProcurementService.iter_unverified_historical_approvals())
        self.stdout.write(f"unverified_count={len(rows)}")
        for row in rows[:limit]:
            self.stdout.write(
                "approval_id={approval_id} pr_id={pr_id} pr_code={pr_code} "
                "amount={amount} currency={currency} scope={decision_scope!r} "
                "basis={amount_basis!r} reason={reason} decided_at={decided_at}".format(
                    **row
                )
            )
        if len(rows) > limit:
            self.stdout.write(f"... truncated, {len(rows) - limit} more")
