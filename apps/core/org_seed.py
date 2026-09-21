"""Seed City Point organization tree from ticket departments (idempotent)."""

from apps.core.organization import Organization, OrgDepartment, OrgQueue
from apps.tickets.models import TicketDepartment, TicketQueue


def seed_city_point_org() -> dict:
    org, _ = Organization.objects.update_or_create(
        code="CP",
        defaults={"name": "City Point Baku", "is_active": True},
    )
    depts = 0
    queues = 0
    for td in TicketDepartment.objects.all():
        dept, _ = OrgDepartment.objects.update_or_create(
            organization=org,
            code=td.code,
            defaults={"name": td.name, "is_active": td.is_active},
        )
        depts += 1
        for tq in TicketQueue.objects.filter(department=td):
            OrgQueue.objects.update_or_create(
                department=dept,
                code=tq.code,
                defaults={"name": tq.name, "is_active": tq.is_active},
            )
            queues += 1
    return {"organization": org.code, "departments": depts, "queues": queues}
