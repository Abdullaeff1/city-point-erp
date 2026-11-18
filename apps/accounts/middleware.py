"""Auth session helpers: forced password + soft 403 → role home."""

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


class MustSetPasswordMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "must_set_password", False):
            path = request.path
            allowed_prefixes = (
                "/accounts/force-password/",
                "/accounts/invite/",
                "/logout/",
                "/login/",
                "/i18n/",
                "/static/",
                "/media/",
            )
            if not any(path.startswith(p) for p in allowed_prefixes):
                return redirect("accounts:force_set_password")
        return self.get_response(request)


class SoftPermissionDeniedMiddleware:
    """Even with DEBUG=True, never show a dead «giriş icazəniz yoxdur» page.

    Django only calls handler403 when DEBUG is False; this middleware covers
    PermissionDenied in all environments by sending the user to their role home
    (or login) via permission_denied_view.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, PermissionDenied):
            from apps.accounts.views import permission_denied_view

            return permission_denied_view(request, exception)
        return None
