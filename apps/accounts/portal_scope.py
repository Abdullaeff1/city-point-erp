"""Session-scoped portal company selection (single | all).

Scope lives in the login session only — not on the User model.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import QuerySet
from django.shortcuts import redirect
from django.urls import reverse

from apps.accounts.models import PortalCompanyMembership, Role, User
from apps.residents.models import CompanyStatus, ResidentCompany

SESSION_MODE_KEY = "portal_scope_mode"
SESSION_IDS_KEY = "portal_company_ids"

MODE_SINGLE = "single"
MODE_ALL = "all"


def memberships_for(user: User) -> QuerySet[PortalCompanyMembership]:
    return (
        PortalCompanyMembership.objects.filter(user=user, is_active=True)
        .select_related("company")
        .order_by("-is_primary", "company__name")
    )


def eligible_companies_qs(user: User) -> QuerySet[ResidentCompany]:
    """Companies the user may select / see in portal (membership + company gates)."""
    return ResidentCompany.objects.filter(
        portal_memberships__user=user,
        portal_memberships__is_active=True,
        status=CompanyStatus.ACTIVE,
        portal_active=True,
        is_internal=False,
    ).distinct().order_by("name")


def eligible_companies_for(user: User) -> list[ResidentCompany]:
    return list(eligible_companies_qs(user))


def eligible_company_ids_for(user: User) -> list[int]:
    return list(eligible_companies_qs(user).values_list("id", flat=True))


@dataclass(frozen=True)
class PortalScope:
    mode: str
    company_ids: tuple[int, ...]

    @property
    def is_all(self) -> bool:
        return self.mode == MODE_ALL

    @property
    def is_single(self) -> bool:
        return self.mode == MODE_SINGLE

    @property
    def single_company_id(self) -> int | None:
        if self.is_single and len(self.company_ids) == 1:
            return self.company_ids[0]
        return None


def clear_portal_scope(request) -> None:
    request.session.pop(SESSION_MODE_KEY, None)
    request.session.pop(SESSION_IDS_KEY, None)
    if hasattr(request, "portal_scope"):
        delattr(request, "portal_scope")
    if hasattr(request, "portal_company_ids"):
        delattr(request, "portal_company_ids")


def set_portal_scope(request, mode: str, company_ids: list[int] | tuple[int, ...]) -> PortalScope:
    ids = tuple(sorted({int(i) for i in company_ids}))
    if mode not in {MODE_SINGLE, MODE_ALL}:
        raise ValueError("invalid_scope_mode")
    if mode == MODE_SINGLE and len(ids) != 1:
        raise ValueError("single_mode_requires_one_company")
    if not ids:
        raise ValueError("empty_scope")
    request.session[SESSION_MODE_KEY] = mode
    request.session[SESSION_IDS_KEY] = list(ids)
    scope = PortalScope(mode=mode, company_ids=ids)
    request.portal_scope = scope
    request.portal_company_ids = list(ids)
    return scope


def get_portal_scope(request) -> PortalScope | None:
    """Return scope if session keys exist and still match current eligibility; else None."""
    mode = request.session.get(SESSION_MODE_KEY)
    raw_ids = request.session.get(SESSION_IDS_KEY)
    if mode not in {MODE_SINGLE, MODE_ALL} or not raw_ids:
        return None

    user = request.user
    if not user.is_authenticated:
        return None

    # Staff browsing portal: no membership gate; trust session only if set
    if getattr(user, "role", None) != Role.RESIDENT_USER:
        ids = tuple(int(i) for i in raw_ids)
        if mode == MODE_SINGLE and len(ids) != 1:
            return None
        scope = PortalScope(mode=mode, company_ids=ids)
        request.portal_scope = scope
        request.portal_company_ids = list(ids)
        return scope

    eligible = set(eligible_company_ids_for(user))
    ids = tuple(sorted(int(i) for i in raw_ids if int(i) in eligible))
    if not ids:
        clear_portal_scope(request)
        return None

    if mode == MODE_SINGLE:
        if len(ids) != 1:
            # session had one id that is no longer eligible
            clear_portal_scope(request)
            return None
        # If eligibility shrunk mid-session for "all", keep remaining; for single ok
    elif mode == MODE_ALL:
        # Re-sync to current eligible intersection; if user selected "all", expand to all eligible
        # only when session still intended all — use intersection of stored ∩ eligible first;
        # if stored was a full snapshot, prefer current full eligible set when it was "all".
        ids = tuple(sorted(eligible))
        if not ids:
            clear_portal_scope(request)
            return None
        request.session[SESSION_IDS_KEY] = list(ids)

    scope = PortalScope(mode=mode, company_ids=ids)
    request.portal_scope = scope
    request.portal_company_ids = list(ids)
    return scope


def require_portal_scope(request):
    """Ensure resident has a valid scope. Returns redirect response or None if OK.

    Staff with portal access skip the chooser (they use resident_company / none).
    """
    user = request.user
    if not user.is_authenticated:
        return redirect("login")
    if user.role != Role.RESIDENT_USER:
        # Staff: expose empty or FK-based ids for views that read portal_company_ids
        company_id = getattr(user, "resident_company_id", None)
        ids = [company_id] if company_id else []
        request.portal_scope = PortalScope(mode=MODE_SINGLE, company_ids=tuple(ids)) if ids else None
        request.portal_company_ids = ids
        return None

    eligible = eligible_companies_for(user)
    if not eligible:
        return None  # mixin raises PermissionDenied

    scope = get_portal_scope(request)
    if scope is not None:
        return None

    if len(eligible) == 1:
        set_portal_scope(request, MODE_SINGLE, [eligible[0].pk])
        return None

    return redirect(reverse("portal:choose_companies"))


def resolve_write_company(request, posted_company_id=None):
    """Company for create operations.

    single scope → that company (ignore posted id unless it matches).
    all scope → posted_company_id required and must be in scope.
    Returns (company|None, error_message|None).
    """
    from django.utils.translation import gettext as _

    scope = getattr(request, "portal_scope", None) or get_portal_scope(request)
    ids = list(getattr(request, "portal_company_ids", None) or [])
    if scope is None and not ids:
        return None, _("Şirkət seçimi tələb olunur.")

    if scope and scope.is_single:
        cid = scope.single_company_id
        company = ResidentCompany.objects.filter(pk=cid).first()
        return company, None

    if posted_company_id in (None, ""):
        return None, _("Şirkət seçin.")
    try:
        cid = int(posted_company_id)
    except (TypeError, ValueError):
        return None, _("Yanlış şirkət.")
    if cid not in ids:
        return None, _("Bu şirkətə icazəniz yoxdur.")
    company = ResidentCompany.objects.filter(pk=cid, id__in=ids).first()
    if not company:
        return None, _("Bu şirkətə icazəniz yoxdur.")
    return company, None


def company_in_scope(request, company_id: int | None) -> bool:
    if company_id is None:
        return False
    ids = getattr(request, "portal_company_ids", None)
    if ids is None:
        scope = get_portal_scope(request)
        ids = list(scope.company_ids) if scope else []
    return int(company_id) in {int(i) for i in ids}
