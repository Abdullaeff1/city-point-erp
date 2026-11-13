from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory
from django.urls import reverse
from apps.accounts.models import Role
from apps.property.models import Space
from apps.portal.views import SpacesView, SpaceDetailView
User = get_user_model()
u = User.objects.get(email="office@asbc.az")
c = Client(); c.force_login(u)
spaces = list(Space.objects.filter(resident=u.resident_company).select_related("floor","resident"))
print("count", len(spaces))
for s in spaces:
    print("code=", s.code, "area=", s.area_code, "floor=", s.floor_id, "res=", s.resident_id)
    try:
        r = c.get(reverse("portal:space_detail", args=[s.code]))
        print("  detail", r.status_code)
        if r.status_code != 200:
            print(r.content.decode()[:1500])
    except Exception as e:
        print("  EXC", type(e), e)
# Render spaces template explicitly with exceptions
rf = RequestFactory()
req = rf.get("/portal/spaces/")
req.user = u
try:
    resp = SpacesView.as_view()(req)
    resp.render()
    print("SpacesView render OK", len(resp.content))
except Exception as e:
    import traceback; traceback.print_exc()
