"""Role → home URL helpers. Never leave an authenticated user on a dead 403 card."""

from __future__ import annotations

from django.shortcuts import redirect
from django.urls import reverse


def home_url_name_for(user) -> str:
    """Named URL for the user's primary landing page after login / wrong-portal.

    Delegates to permission-validated department landing (Phase 3).
    """
    from apps.accounts.nav import resolve_landing_url_name

    return resolve_landing_url_name(user)


def home_url_for(user) -> str:
    return reverse(home_url_name_for(user))


def redirect_home(user):
    return redirect(home_url_name_for(user))
