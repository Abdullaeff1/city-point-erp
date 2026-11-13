from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

u = get_user_model().objects.get(username="security")
c = Client()
c.force_login(u)
url = reverse("security:guests")
today = timezone.localdate()
week_start = today - timedelta(days=today.weekday())
month_start = today.replace(day=1)
checks = [
    ("today", {"range": "today"}, today, today),
    ("week", {"range": "week"}, week_start, today),
    ("month", {"range": "month"}, month_start, today),
    (
        "custom",
        {"range": "custom", "from": "2026-10-01", "to": "2026-10-20"},
        date(2026, 10, 1),
        date(2026, 10, 20),
    ),
]
for name, params, exp_from, exp_to in checks:
    r = c.get(url, params)
    ctx = r.context_data if hasattr(r, "context_data") else None
    if ctx is None and r.context is not None:
        ctx = r.context[-1] if isinstance(r.context, list) else r.context
    preset = ctx.get("export_preset") if ctx else None
    got_from = ctx.get("export_from") if ctx else None
    got_to = ctx.get("export_to") if ctx else None
    ok = (
        r.status_code == 200
        and preset == name
        and got_from == exp_from
        and got_to == exp_to
    )
    print(
        name,
        "OK" if ok else "FAIL",
        "http",
        r.status_code,
        "preset",
        preset,
        got_from,
        got_to,
        "redirect",
        r.get("Location"),
    )
