"""Helpers for portal tests — create memberships via service (not raw FK alone)."""

from __future__ import annotations

from django.urls import reverse

from apps.accounts.membership import add_membership, set_user_memberships
from apps.accounts.routing import home_url_for


def ensure_portal_membership(user, company, *, primary: bool = True):
    """Attach an active portal membership and sync resident_company."""
    return add_membership(user=user, company=company, is_primary=primary)


def ensure_portal_memberships(user, companies, *, primary_company=None):
    companies = list(companies)
    if not companies:
        raise ValueError("companies required")
    primary = primary_company or companies[0]
    return set_user_memberships(
        user=user,
        company_ids=[c.pk for c in companies],
        primary_company_id=primary.pk,
        replace=True,
    )


def assert_soft_denied(
    test_case,
    client,
    response,
    user,
    *,
    expected_url: str | None = None,
    protected_markers: tuple[str, ...] = (),
    follow: bool = True,
):
    """Browser soft-deny contract: 302 → role home; protected content absent.

    SoftPermissionDeniedMiddleware and portal/role mixins send authenticated
    users to their landing instead of a dead 403 HTML page. Tests must pin the
    destination and confirm the protected surface is not rendered after follow.
    """
    test_case.assertEqual(
        response.status_code,
        302,
        f"expected soft-deny redirect, got {response.status_code}",
    )
    dest = expected_url if expected_url is not None else home_url_for(user)
    test_case.assertEqual(response.url, dest)
    if follow:
        home = client.get(response.url, follow=True)
        test_case.assertEqual(home.status_code, 200)
        for marker in protected_markers:
            test_case.assertNotContains(home, marker)
    return response


def assert_login_redirect(test_case, response, *, fragment: str = "/login/"):
    """Unauthenticated / logged-out gate → login URL (not a 403 body)."""
    test_case.assertEqual(response.status_code, 302)
    test_case.assertIn(fragment, response["Location"])
