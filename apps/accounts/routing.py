"""Role → home URL helpers. Never leave an authenticated user on a dead 403 card."""

from __future__ import annotations

from django.shortcuts import redirect
from django.urls import reverse

from apps.accounts.models import Role


def home_url_name_for(user) -> str:
    """Named URL for the user's primary landing page after login / wrong-portal."""
    role = getattr(user, "role", None)
    if role == Role.RESIDENT_USER:
        return "portal:home"
    if role == Role.SECURITY:
        return "security:home"
    if role == Role.ACCOUNTANT:
        return "finance:home"
    if role == Role.RECEPTION:
        return "erp:reception"
    if role == Role.SERVICE_DESK:
        return "erp:tickets"
    if role == Role.SALES:
        return "erp:crm_leads"
    if role == Role.PROPERTY_FM:
        return "erp:dashboard"
    return "erp:dashboard"


def home_url_for(user) -> str:
    return reverse(home_url_name_for(user))


def redirect_home(user):
    return redirect(home_url_name_for(user))
