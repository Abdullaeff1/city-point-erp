"""IT / Administration operator screens — read-only staff directory."""

from __future__ import annotations

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from apps.accounts.mixins import PermissionRequiredMixin, StaffRequiredMixin
from apps.accounts.models import Role, User
from apps.erp.it_access import can_access_erp_audit, staff_users_queryset
from apps.rbac.services import user_has_permission

PAGE_SIZE = 40


class StaffUserListView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    """Read-only ERP login directory. Mutations remain in Django Admin."""

    template_name = "erp/staff_users.html"
    permission_required = ("user.view", "user.admin")
    permission_denied_message = "İstifadəçi siyahısına baxış icazəniz yoxdur."

    def get_queryset(self):
        qs = staff_users_queryset()
        q = (self.request.GET.get("q") or "").strip()
        role = (self.request.GET.get("role") or "").strip()
        status = (self.request.GET.get("status") or "").strip().lower()
        if q:
            qs = qs.filter(
                Q(username__icontains=q)
                | Q(email__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
            )
        if role in {c.value for c in Role}:
            qs = qs.filter(role=role)
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = self.get_queryset()
        page = Paginator(qs, PAGE_SIZE).get_page(self.request.GET.get("page") or "1")
        ctx.update(
            {
                "page_obj": page,
                "users_page": page,
                "q": (self.request.GET.get("q") or "").strip(),
                "role": (self.request.GET.get("role") or "").strip(),
                "status": (self.request.GET.get("status") or "").strip().lower(),
                "role_choices": Role.choices,
                "can_admin_users": user_has_permission(self.request.user, "user.admin"),
                "can_erp_audit": can_access_erp_audit(self.request.user, self.request),
                "total_count": qs.count(),
            }
        )
        return ctx


class StaffUserDetailView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/staff_user_detail.html"
    permission_required = ("user.view", "user.admin")
    permission_denied_message = "İstifadəçi kartına baxış icazəniz yoxdur."

    def get_object(self):
        return get_object_or_404(staff_users_queryset(), pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        target = self.get_object()
        ctx.update(
            {
                "target_user": target,
                "can_admin_users": user_has_permission(self.request.user, "user.admin"),
                "admin_change_url": f"/admin/accounts/user/{target.pk}/change/",
            }
        )
        return ctx
