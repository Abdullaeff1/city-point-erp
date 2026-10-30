"""Helpers for portal tests — create memberships via service (not raw FK alone)."""

from __future__ import annotations

from apps.accounts.membership import add_membership, set_user_memberships


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
