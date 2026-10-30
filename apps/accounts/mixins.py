from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _

from apps.accounts.models import Role, STAFF_ROLES, SECURITY_PORTAL_ROLES
from apps.accounts.portal_scope import eligible_companies_for, require_portal_scope


class StaffRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_erp():
            raise PermissionDenied("ERP yalnız əməkdaşlar üçündür.")
        return super().dispatch(request, *args, **kwargs)


class ResidentPortalMixin(LoginRequiredMixin):
    """Portal pages that require a valid company scope for resident users."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_portal():
            raise PermissionDenied("Portal girişinə icazə yoxdur.")
        if request.user.role == Role.RESIDENT_USER:
            eligible = eligible_companies_for(request.user)
            if not eligible:
                raise PermissionDenied(_("Rezident şirkəti təyin olunmayıb və ya portal bağlıdır."))
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
            raise PermissionDenied(_("Şirkət seçimi yalnız rezidentlər üçündür."))
        if not eligible_companies_for(request.user):
            raise PermissionDenied(_("Rezident şirkəti təyin olunmayıb və ya portal bağlıdır."))
        return super().dispatch(request, *args, **kwargs)


class SecurityPortalMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_security_portal():
            raise PermissionDenied("Təhlükəsizlik portalına giriş icazəniz yoxdur.")
        return super().dispatch(request, *args, **kwargs)


class RoleRequiredMixin(StaffRequiredMixin):
    allowed_roles: tuple[str, ...] = tuple(r for r in STAFF_ROLES if r != Role.SECURITY)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_erp():
            raise PermissionDenied("ERP yalnız əməkdaşlar üçündür.")
        if request.user.role not in {Role.ADMIN, Role.MANAGEMENT, *self.allowed_roles}:
            raise PermissionDenied("Bu bölməyə giriş icazəniz yoxdur.")
        return super(StaffRequiredMixin, self).dispatch(request, *args, **kwargs)
