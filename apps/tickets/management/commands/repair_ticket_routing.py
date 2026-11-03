"""Repair ticket routing + staff department links for server deploy.

Usage:
  python manage.py repair_ticket_routing
  python manage.py repair_ticket_routing --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Role, User
from apps.tickets.models import CLOSED_STATUSES, RoutingRule, Ticket, TicketDepartment
from apps.tickets.routing import ROLE_DEFAULT_DEPARTMENT
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import resolve_routing_rule, route_ticket


class Command(BaseCommand):
    help = (
        "Seed taxonomy/routing rules, bind staff roles to ticket departments, "
        "and re-route open tickets whose department does not match the subcategory rule."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without writing.",
        )
        parser.add_argument(
            "--include-closed",
            action="store_true",
            help="Also re-route closed/resolved tickets.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry = options["dry_run"]
        include_closed = options["include_closed"]
        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved."))

        tax = seed_ticket_taxonomy()
        self.stdout.write(
            f"Taxonomy: {len(tax['categories'])} categories, "
            f"{len(tax['subcategories'])} subcategories, "
            f"{RoutingRule.objects.filter(is_active=True).count()} active rules."
        )

        dept_by_code = {d.code: d for d in TicketDepartment.objects.filter(is_active=True)}
        staff_fixed = 0
        for role, code in ROLE_DEFAULT_DEPARTMENT.items():
            dept = dept_by_code.get(code)
            if not dept:
                self.stdout.write(self.style.ERROR(f"Missing department code={code}"))
                continue
            qs = User.objects.filter(role=role, is_active=True).exclude(ticket_department_id=dept.pk)
            n = qs.count()
            if n:
                self.stdout.write(f"Staff {role}: set ticket_department={code} for {n} user(s)")
                if not dry:
                    qs.update(ticket_department=dept)
                staff_fixed += n

        tickets = Ticket.objects.select_related(
            "subcategory", "category", "department", "queue"
        ).order_by("id")
        if not include_closed:
            tickets = tickets.exclude(status__in=CLOSED_STATUSES)

        rerouted = 0
        orphan_fixed = 0
        for ticket in tickets.iterator(chunk_size=200):
            rule = resolve_routing_rule(ticket.subcategory) if ticket.subcategory_id else None
            target_dept_id = rule.department_id if rule else None
            needs = False
            if ticket.department_id is None:
                needs = True
                orphan_fixed += 1
            elif target_dept_id and ticket.department_id != target_dept_id:
                needs = True
            if not needs:
                continue
            self.stdout.write(
                f"  {ticket.code}: dept={getattr(ticket.department, 'code', None)} "
                f"cat={getattr(ticket.category, 'slug', None)} "
                f"sub={getattr(ticket.subcategory, 'slug', None)} "
                f"→ expected={getattr(rule.department, 'code', None) if rule else 'category-fallback'}"
            )
            if not dry:
                route_ticket(ticket, actor=None, note="repair_ticket_routing")
            rerouted += 1

        if dry:
            transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. staff_fixed={staff_fixed} tickets_rerouted={rerouted} "
                f"(orphans={orphan_fixed})."
            )
        )
