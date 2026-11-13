from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path

from apps.accounts.views import login_view, logout_view, post_login
from apps.core.media_views import media_serve
from apps.tickets.views_attachments import ticket_attachment_download

handler403 = "apps.accounts.views.permission_denied_view"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("go/", post_login, name="post_login"),
    path("accounts/", include("apps.accounts.urls")),
    path("portal/", include("apps.portal.urls")),
    path("security/", include("apps.security.urls")),
    path("finance/", include("apps.finance.urls")),
    path("management/", include("apps.management.urls")),
    path("erp/", include("apps.erp.urls")),
    path("api/", include("apps.api.urls")),
    path(
        "tickets/attachments/<int:pk>/",
        ticket_attachment_download,
        name="ticket_attachment_download",
    ),
    path("", post_login),
]

# Always register gated media handler in DEBUG; in production nginx should also
# block /media/documents/ (see docs/deployment/UPDATE_resident_docs.md).
if settings.DEBUG:
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", media_serve, name="media"),
    ]
