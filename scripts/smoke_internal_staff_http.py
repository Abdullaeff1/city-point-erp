"""One-shot HTTP smoke for CP internal-staff pages (run via manage.py shell <)."""
from django.contrib.auth import get_user_model
from django.test import Client

from apps.accounts.models import Role
from apps.residents.models import ResidentEmployee

User = get_user_model()
u = User.objects.filter(role=Role.ADMIN, is_active=True).first()
emp = ResidentEmployee.objects.filter(pk=610).first() or ResidentEmployee.objects.filter(
    company__slug="city-point", is_active=True
).first()
c = Client()
c.force_login(u)
paths = [
    "/erp/internal-staff/access/",
    "/erp/internal-staff/access/?late=1",
    f"/erp/internal-staff/access/{emp.pk}/",
    f"/erp/internal-staff/access/{emp.pk}/?range=week",
    f"/erp/internal-staff/access/{emp.pk}/?range=month",
    f"/erp/internal-staff/access/{emp.pk}/whatsapp-preview/",
    f"/erp/internal-staff/access/{emp.pk}/attendance.xlsx?range=week",
]
for path in paths:
    r = c.get(path)
    body = r.content.decode("utf-8", "replace") if r.content else ""
    flag = "REVERR" if "NoReverseMatch" in body else "ok"
    print(f"{r.status_code}\t{flag}\t{path}")
