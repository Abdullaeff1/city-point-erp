from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from apps.accounts.models import Role, STAFF_ROLES
from apps.accounts.portal_scope import eligible_companies_for, require_portal_scope
from apps.accounts.routing import redirect_home
from apps.rbac.services import require_any_permission, require_permission, user_has_permission


def _portal_home_redirect(user):
    """Send dedicated-portal roles to their home instead of a bare 403 on ERP."""
    role = getattr(user, "role", None)
    if role == Role.ACCOUNTANT:
        return redirect("finance:home")
    if role == Role.SECURITY:
        return redirect("security:home")
    return None


class StaffRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_erp():
            dest = _portal_home_redirect(request.user)
            if dest is not None:
                return dest
            return redirect_home(request.user)
        return super().dispatch(request, *args, **kwargs)


class ResidentPortalMixin(LoginRequiredMixin):
    """Portal pages that require a valid company scope for resident users."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_portal():
            dest = _portal_home_redirect(request.user)
            if dest is not None:
                return dest
            return redirect_home(request.user)
        if request.user.role == Role.RESIDENT_USER:
            eligible = eligible_companies_for(request.user)
            if not eligible:
                logout(request)
                return redirect("login")
            redirect_response = require_portal_scope(request)
            if redirect_response is not None:
                return redirect_response
        else:
            # Staff browsing portal — attach empty/FK scope for view helpers
            require_portal_scope(request)
        return super().dispatch(request, *args, **kwargs)


class ResidentChooserMixin(LoginRequiredMixin):
    """Company selector — authenticated resident, no scope required (avoids redirect loop)."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.role != Role.RESIDENT_USER:
            return redirect_home(request.user)
        if not eligible_companies_for(request.user):
            logout(request)
            return redirect("login")
        return super().dispatch(request, *args, **kwargs)


class SecurityPortalMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_security_portal():
            return redirect_home(request.user)
        require_permission(
            request.user,
            "security.view",
            message=_("Təhlükəsizlik portalına giriş icazəniz yoxdur."),
        )
        return super().dispatch(request, *args, **kwargs)


class FinancePortalMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_finance_portal():
            return redirect_home(request.user)
        require_permission(
            request.user,
            "finance.view",
            message=_("Maliyyə portalına giriş icazəniz yoxdur."),
        )
        return super().dispatch(request, *args, **kwargs)


class CrmAccessMixin(LoginRequiredMixin):
    """CRM view access — sales mutate; management/accountant view (Admin out, A.10); approve separate."""

    require_mutate: bool = False
    require_approve: bool = False
    require_accountant: bool = False

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        from apps.crm.access import (
            can_approve_offer,
            can_mutate_crm,
            can_review_lease_application,
            can_view_crm,
        )

        if not can_view_crm(request.user):
            return redirect_home(request.user)
        if self.require_mutate and not can_mutate_crm(request.user):
            return redirect_home(request.user)
        if self.require_approve and not can_approve_offer(request.user):
            return redirect_home(request.user)
        if self.require_accountant and not can_review_lease_application(request.user):
            return redirect_home(request.user)
        return super().dispatch(request, *args, **kwargs)


class RoleRequiredMixin(StaffRequiredMixin):
    allowed_roles: tuple[str, ...] = tuple(
        r for r in STAFF_ROLES if r not in (Role.SECURITY, Role.ACCOUNTANT)
    )
    # Rəhbərlik ERP-də nəticə RO görür; əməliyyat mutate view-larda False edin.
    allow_management: bool = True

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_erp():
            dest = _portal_home_redirect(request.user)
            if dest is not None:
                return dest
            return redirect_home(request.user)
        allowed = {Role.ADMIN, *self.allowed_roles}
        if self.allow_management:
            allowed.add(Role.MANAGEMENT)
        if request.user.role not in allowed:
            return redirect_home(request.user)
        return super(StaffRequiredMixin, self).dispatch(request, *args, **kwargs)


class PermissionRequiredMixin(LoginRequiredMixin):
    """Backend permission gate (dual-use with role mixins). Any-of when tuple/list."""

    permission_required: str | tuple[str, ...] | list[str] = ()
    permission_denied_message: str = ""

    def get_permission_required(self) -> tuple[str, ...]:
        req = self.permission_required
        if not req:
            return ()
        if isinstance(req, str):
            return (req,)
        return tuple(req)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        codes = self.get_permission_required()
        if codes:
            msg = self.permission_denied_message or None
            if len(codes) == 1:
                require_permission(request.user, codes[0], message=msg)
            else:
                require_any_permission(request.user, *codes, message=msg)
        return super().dispatch(request, *args, **kwargs)


class HasPermissionMixin:
    """Optional context helper for templates (does not enforce)."""

    def has_perm(self, code: str) -> bool:
        user = getattr(self, "request", None) and self.request.user
        return user_has_permission(user, code)
