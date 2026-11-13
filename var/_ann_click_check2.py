from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from apps.accounts.models import Role
import re, json
User = get_user_model()
u = User.objects.filter(role=Role.RESIDENT_USER).first()
c = Client(); c.force_login(u)
r = c.get(reverse("portal:announcements"))
html = r.content.decode()
m = re.search(r'id="announcement-data"[^>]*>(.*?)</script>', html, re.S)
print("json_match", bool(m))
if m:
    raw = m.group(1)
    print("raw_prefix", raw[:120])
    try:
        data = json.loads(raw)
        print("parsed", len(data), [x.get("id") for x in data])
    except Exception as e:
        print("parse_err", e)
# check if guest-detail CSS might hide dialog
print("dialog snippet", re.search(r'<dialog[\s\S]*?</dialog>', html).group(0)[:300] if re.search(r'<dialog', html) else None)
