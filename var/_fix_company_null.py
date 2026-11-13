from django.db import connection
from django.utils import timezone

from apps.integrations import axtrax_events_sync as m
from apps.integrations.axtrax_events_sync import _snapshot_company
from apps.residents.models import AccessEvent, ResidentEmployee

with connection.cursor() as c:
    c.execute(
        """
        SELECT column_name, is_nullable, column_default, data_type
        FROM information_schema.columns
        WHERE table_name='residents_accessevent'
          AND column_name IN ('company_id', 'company_name')
        """
    )
    print("cols", c.fetchall())

emp = ResidentEmployee.objects.filter(pk=368).select_related("company").first()
print("emp", emp, "co_id", getattr(emp, "company_id", None))
print("snap", _snapshot_company(emp))

import inspect

src = inspect.getsource(m.sync_event_rows)
print("has_row_errors", "row_errors" in src)
print("has_or_empty", 'company_name or ""' in src or "company_name or ''" in src)

e = AccessEvent(
    employee=emp,
    event_type="in",
    result="granted",
    occurred_at=timezone.now(),
    employee_name="test",
    card_number="003904",
    company_id=None,
    company_name="",
)
e.save()
print("saved_empty_name", e.pk, repr(e.company_name))
AccessEvent.objects.filter(pk=e.pk).delete()

# What if company_name omitted?
try:
    e2 = AccessEvent.objects.create(
        employee=emp,
        event_type="in",
        result="granted",
        occurred_at=timezone.now(),
        employee_name="test2",
        card_number="003904",
        company_id=None,
        # company_name omitted
    )
    print("omit_ok", e2.pk, repr(e2.company_name))
    e2.delete()
except Exception as ex:
    print("omit_fail", type(ex).__name__, ex)
