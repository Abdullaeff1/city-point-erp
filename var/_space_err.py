from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from apps.accounts.models import Role
User = get_user_model()
u = User.objects.filter(role=Role.RESIDENT_USER).first()
print("user", u, getattr(u, "resident_company_id", None))
c = Client(); c.force_login(u)
for name in ["spaces", "home"]:
    r = c.get(reverse(f"portal:{name}"))
    print(name, r.status_code)
    if r.status_code >= 400:
        print(r.content.decode()[:2000])
# try first space detail if any
from apps.property.models import Space
sp = Space.objects.filter(resident_id=u.resident_company_id).first()
print("space", sp)
if sp:
    r = c.get(reverse("portal:space_detail", args=[sp.code]))
    print("detail", r.status_code)
    if r.status_code >= 400:
        print(r.content.decode()[:3000])
    elif r.status_code == 200:
        print("detail ok", sp.code)
