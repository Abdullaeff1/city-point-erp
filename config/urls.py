from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.accounts.views import login_view, logout_view, post_login

handler403 = "django.views.defaults.permission_denied"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("go/", post_login, name="post_login"),
    path("portal/", include("apps.portal.urls")),
    path("erp/", include("apps.erp.urls")),
    path("", post_login),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
