"""Redirect users who must set a password after invite/admin reset."""

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
                "/i18n/",
                "/static/",
                "/media/",
            )
            if not any(path.startswith(p) for p in allowed_prefixes):
                return redirect("accounts:force_set_password")
        return self.get_response(request)
