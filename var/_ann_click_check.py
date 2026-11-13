from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from apps.accounts.models import Role
from apps.residents.models import ResidentCompany

User = get_user_model()
u = User.objects.filter(role=Role.RESIDENT_USER).first()
c = Client()
c.force_login(u)
r = c.get(reverse("portal:announcements"))
html = r.content.decode()
print("status", r.status_code)
print("has dialog", "announcement-dialog" in html)
print("has data", "announcement-data" in html)
print("has script openAnnouncement", "openAnnouncement" in html)
print("card count", html.count("data-announcement-id"))
print("payload len", len(r.context.get("announcement_payload") or []))
# show script start snippet
idx = html.find("announcement-data")
print(html[idx:idx+200] if idx>=0 else "no data el")
