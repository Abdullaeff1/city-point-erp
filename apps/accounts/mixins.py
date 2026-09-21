from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from apps.accounts.models import Role, STAFF_ROLES, SECURITY_PORTAL_ROLES


class StaffRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_erp():
            raise PermissionDenied("ERP yalnız əməkdaşlar üçündür.")
        return super().dispatch(request, *args, **kwargs)


class ResidentPortalMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.role == Role.RESIDENT_USER:
            company = request.user.resident_company
            if not company:
                raise PermissionDenied("Rezident şirkəti təyin olunmayıb.")
            if not company.portal_active:
                raise PermissionDenied("Bu şirkət üçün portal müvəqqəti bağlanıb.")
        if not request.user.can_access_portal():
            raise PermissionDenied("Portal girişinə icazə yoxdur.")
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
