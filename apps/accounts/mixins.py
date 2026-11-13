from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from apps.accounts.models import Role, STAFF_ROLES
from apps.accounts.portal_scope import eligible_companies_for, require_portal_scope
from apps.accounts.routing import redirect_home


def _portal_home_redirect(user):
    """Send dedicated-portal roles to their home instead of a bare 403 on ERP."""
    if getattr(user, "role", None) == Role.ACCOUNTANT:
        return redirect("finance:home")
    if getattr(user, "role", None) == Role.SECURITY:
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
        return super().dispatch(request, *args, **kwargs)


class FinancePortalMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_finance_portal():
            return redirect_home(request.user)
        return super().dispatch(request, *args, **kwargs)


class CrmAccessMixin(LoginRequiredMixin):
    """CRM view access — sales/management/admin/accountant; reception → home."""

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

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_erp():
            dest = _portal_home_redirect(request.user)
            if dest is not None:
                return dest
            return redirect_home(request.user)
        if request.user.role not in {Role.ADMIN, Role.MANAGEMENT, *self.allowed_roles}:
            return redirect_home(request.user)
        return super(StaffRequiredMixin, self).dispatch(request, *args, **kwargs)
