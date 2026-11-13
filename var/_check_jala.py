from collections import Counter
from datetime import datetime

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Max, Min
from django.utils import timezone as tz

from apps.integrations.models import ExternalIdentity
from apps.residents.models import AccessEvent, ResidentEmployee

# Find Jalə
cands = list(
    ResidentEmployee.objects.filter(full_name__icontains="Mirzəməmmədova").select_related(
        "company"
    )
)
print("=== Name matches ===")
for e in cands:
    print(
        f"pk={e.pk} name={e.full_name!r} company={e.company.slug} "
        f"card={e.card_number!r} active={e.is_active}"
    )

emp = next((e for e in cands if e.card_number == "006109"), cands[0] if cands else None)
if not emp:
    raise SystemExit("not found")

print()
print(f"=== Focus pk={emp.pk} ===")
ct = ContentType.objects.get_for_model(ResidentEmployee)
ext = list(
    ExternalIdentity.objects.filter(
        system="axtraxng", entity_type=ct, entity_id=emp.pk
    ).values("external_id", "last_sync_at", "created_at" if False else "id")
)
# created_at may not exist
print(
    "ExternalIdentity:",
    list(
        ExternalIdentity.objects.filter(
            system="axtraxng", entity_type=ct, entity_id=emp.pk
        ).values_list("external_id", "last_sync_at", "last_status")
    ),
)

# Who else was ever linked to emp:1075?
print()
print("=== All ExternalIdentity emp:1075 ===")
for row in ExternalIdentity.objects.filter(
    system="axtraxng", external_id="emp:1075"
).values("entity_id", "last_sync_at", "last_status"):
    other = ResidentEmployee.objects.filter(pk=row["entity_id"]).select_related("company").first()
    print(row, "->", getattr(other, "full_name", None), getattr(getattr(other, "company", None), "slug", None))

print()
print("=== Events for employee", emp.pk, "by card ===")
qs = AccessEvent.objects.filter(employee_id=emp.pk)
print("total", qs.count())
print(
    list(
        qs.values("card_number")
        .annotate(c=Count("id"), mn=Min("occurred_at"), mx=Max("occurred_at"))
        .order_by("mn")
    )
)
print(
    "employee_name snapshots:",
    list(
        qs.values("employee_name")
        .annotate(c=Count("id"))
        .order_by("-c")[:10]
    ),
)
print(
    "axtrax_employee_id:",
    list(qs.values("axtrax_employee_id").annotate(c=Count("id"))),
)
print(
    "company snapshots:",
    list(qs.values("company_id", "company_name").annotate(c=Count("id"))),
)

# 006297 holders
print()
print("=== Who has / had card 006297 in events ===")
for row in (
    AccessEvent.objects.filter(card_number="006297")
    .values("employee_id", "employee_name", "axtrax_employee_id")
    .annotate(c=Count("id"), mn=Min("occurred_at"), mx=Max("occurred_at"))
    .order_by("-c")[:15]
):
    e = ResidentEmployee.objects.filter(pk=row["employee_id"]).first() if row["employee_id"] else None
    print(row, "current=", getattr(e, "full_name", None), "card_now=", getattr(e, "card_number", None))

print()
print("=== Current ResidentEmployee with card 006297 ===")
for e in ResidentEmployee.objects.filter(card_number="006297").select_related("company"):
    print(e.pk, e.full_name, e.company.slug, e.is_active)

# Oct events detail for emp before 29
print()
print("=== Sample Oct 1-28 events for Jalə (first 8) ===")
start = tz.make_aware(datetime(2026, 10, 1))
cut = tz.make_aware(datetime(2026, 10, 29))
for e in AccessEvent.objects.filter(
    employee=emp, occurred_at__gte=start, occurred_at__lt=cut
).order_by("occurred_at")[:8]:
    print(
        tz.localtime(e.occurred_at),
        e.event_type,
        "card=",
        e.card_number,
        "name=",
        e.employee_name,
        "ax=",
        e.axtrax_employee_id,
        "co=",
        e.company_name,
    )

print()
print("=== emp:1075 events NOT on Jalə pk ===")
wrong = AccessEvent.objects.filter(axtrax_employee_id=1075).exclude(employee_id=emp.pk)
print("count", wrong.count())
print(list(wrong.values("employee_id", "employee_name").annotate(c=Count("id"))[:10]))
