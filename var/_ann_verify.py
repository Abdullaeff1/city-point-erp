from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from apps.accounts.models import Role
User = get_user_model()
u = User.objects.filter(role=Role.RESIDENT_USER).first()
c = Client(); c.force_login(u)
html = c.get(reverse("portal:announcements")).content.decode()
checks = [
 "data-announcement-open=",
 "announcement-source",
 "announcement-dialog",
 "showModal",
 "announcement-list",
 "block.super",  # should NOT appear
]
for k in checks:
 print(k, k in html)
# script should be after cp-shell close
print("script_after_shell", html.find("cp-shell") < html.find("showModal"))
print("dialog_css_class", 'class="announcement-dialog"' in html)
