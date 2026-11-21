"""Warehouse / inventory operator UI (Phase 4.4.2.2)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from apps.accounts.mixins import PermissionRequiredMixin, StaffRequiredMixin
from apps.core.services import DomainError
from apps.rbac.services import require_permission, user_has_permission
from apps.warehouse.access import can_mutate_warehouse
from apps.warehouse.models import SKU, Stock, StockMovement, Warehouse, IssueStatus, WarehouseIssue
from apps.warehouse.services import (
    adjust_stock,
    can_confirm_warehouse_issue,
    confirm_issue,
    create_sku,
    update_sku,
)


PAGE_SIZE = 50
MOVEMENT_PAGE_SIZE = 40


class WarehouseListView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/warehouse.html"
    permission_required = "warehouse.view"
    permission_denied_message = "Anbara baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        request = self.request
        q = (request.GET.get("q") or "").strip()
        warehouse_id = (request.GET.get("warehouse") or "").strip()
        low_only = request.GET.get("low") == "1"
        sku_page = request.GET.get("sku_page") or "1"
        stock_page = request.GET.get("stock_page") or "1"
        mov_page = request.GET.get("mov_page") or "1"

        warehouses = Warehouse.objects.order_by("code")
        sku_qs = SKU.objects.all().order_by("code")
        stock_qs = Stock.objects.select_related("sku", "warehouse", "bin").order_by(
            "sku__code", "warehouse__code"
        )
        movement_qs = StockMovement.objects.select_related("sku", "warehouse", "work_order").order_by(
            "-created_at"
        )

        if q:
            sku_qs = sku_qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
            stock_qs = stock_qs.filter(
                Q(sku__code__icontains=q) | Q(sku__name__icontains=q) | Q(warehouse__code__icontains=q)
            )
            movement_qs = movement_qs.filter(
                Q(sku__code__icontains=q) | Q(reference__icontains=q) | Q(notes__icontains=q)
            )
        if warehouse_id.isdigit():
            stock_qs = stock_qs.filter(warehouse_id=int(warehouse_id))
            movement_qs = movement_qs.filter(warehouse_id=int(warehouse_id))

        low_stock_qs = (
            Stock.objects.select_related("sku", "warehouse")
            .filter(sku__reorder_level__gt=0)
            .filter(quantity__lte=F("sku__reorder_level"))
            .order_by("sku__code")
        )
        if warehouse_id.isdigit():
            low_stock_qs = low_stock_qs.filter(warehouse_id=int(warehouse_id))
        if q:
            low_stock_qs = low_stock_qs.filter(
                Q(sku__code__icontains=q) | Q(sku__name__icontains=q)
            )
        if low_only:
            stock_qs = stock_qs.filter(sku__reorder_level__gt=0).filter(
                quantity__lte=F("sku__reorder_level")
            )

        sku_pager = Paginator(sku_qs, PAGE_SIZE)
        stock_pager = Paginator(stock_qs, PAGE_SIZE)
        mov_pager = Paginator(movement_qs, MOVEMENT_PAGE_SIZE)

        can_edit = can_mutate_warehouse(request.user)
        ctx.update(
            {
                "q": q,
                "warehouse_id": warehouse_id,
                "low_only": low_only,
                "warehouses": warehouses,
                "skus_page": sku_pager.get_page(sku_page),
                "stocks_page": stock_pager.get_page(stock_page),
                "movements_page": mov_pager.get_page(mov_page),
                "low_stock": list(low_stock_qs[:100]),
                "low_stock_count": low_stock_qs.count(),
                "open_issues": WarehouseIssue.objects.filter(status=IssueStatus.OPEN)
                .select_related("work_order", "warehouse")
                .prefetch_related("lines__sku"),
                "can_confirm_issue": can_confirm_warehouse_issue(request.user),
                "can_edit_warehouse": can_edit,
                "can_create_pr": user_has_permission(request.user, "procurement.edit") and can_edit,
                "submit_token": uuid.uuid4().hex,
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        from apps.procurement.services import ProcurementService

        require_permission(
            request.user,
            "warehouse.edit",
            message=_("Anbar əməliyyatı icazəniz yoxdur."),
        )
        if not can_mutate_warehouse(request.user):
            raise PermissionDenied(_("Anbar əməliyyatı icazəniz yoxdur."))

        action = request.POST.get("action")
        token = (request.POST.get("submit_token") or "").strip()
        session_key = f"wh_action_{action}"
        if token and request.session.get(session_key) == token:
            messages.info(request, _("Bu forma artıq göndərilib."))
            return redirect("erp:warehouse")

        try:
            if action == "create_pr":
                require_permission(
                    request.user,
                    "procurement.edit",
                    message=_("Satınalma sorğusu yaratmaq icazəniz yoxdur."),
                )
                stock = get_object_or_404(Stock, pk=request.POST.get("stock_id"))
                pr = ProcurementService.create_pr_from_low_stock(
                    stock=stock, requested_by=request.user
                )
                messages.success(request, _("PR yaradıldı: %(code)s") % {"code": pr.code})
            elif action == "confirm_issue":
                if not can_confirm_warehouse_issue(request.user):
                    raise PermissionDenied(_("Anbar çıxışını yalnız anbar təsdiqləyir."))
                issue = get_object_or_404(WarehouseIssue, pk=request.POST.get("issue_id"))
                posted = []
                missing = False
                for line in issue.lines.all():
                    raw_qty = request.POST.get(f"issued_qty_{line.pk}")
                    if raw_qty is None or str(raw_qty).strip() == "":
                        missing = True
                        break
                    posted.append(
                        {
                            "id": line.pk,
                            "issued_qty": str(raw_qty).replace(",", "."),
                            "unit_cost": str(
                                request.POST.get(f"unit_cost_{line.pk}") or "0"
                            ).replace(",", "."),
                        }
                    )
                if missing:
                    messages.error(request, _("Hər sətir üçün faktiki miqdar yazılmalıdır."))
                    return redirect("erp:warehouse")
                confirm_issue(issue, actor=request.user, lines=posted)
                messages.success(request, _("%(code)s üzrə çıxış təsdiqləndi.") % {"code": issue.code})
            elif action == "create_sku":
                sku = create_sku(
                    code=request.POST.get("code", ""),
                    name=request.POST.get("name", ""),
                    unit=request.POST.get("unit") or "pcs",
                    reorder_level=request.POST.get("reorder_level") or "0",
                    actor=request.user,
                )
                messages.success(request, _("SKU yaradıldı: %(code)s") % {"code": sku.code})
                if token:
                    request.session[session_key] = token
                    request.session.modified = True
                return redirect("erp:warehouse_sku_detail", code=sku.code)
            elif action == "adjust_stock":
                sku = get_object_or_404(SKU, pk=request.POST.get("sku_id"))
                warehouse = get_object_or_404(Warehouse, pk=request.POST.get("warehouse_id"))
                adjust_stock(
                    sku=sku,
                    warehouse=warehouse,
                    new_quantity=request.POST.get("quantity"),
                    reason=request.POST.get("reason", ""),
                    actor=request.user,
                )
                messages.success(
                    request,
                    _("Stok düzəldildi: %(sku)s @ %(wh)s")
                    % {"sku": sku.code, "wh": warehouse.code},
                )
            else:
                messages.error(request, _("Naməlum əməliyyat."))
        except (DomainError, ValueError) as exc:
            messages.error(request, str(exc))
            return redirect(request.get_full_path() or reverse("erp:warehouse"))

        if token:
            request.session[session_key] = token
            request.session.modified = True
        return redirect("erp:warehouse")


class WarehouseSkuDetailView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/warehouse_sku_detail.html"
    permission_required = "warehouse.view"
    permission_denied_message = "Anbara baxış icazəniz yoxdur."

    def get_sku(self):
        return get_object_or_404(SKU, code=self.kwargs["code"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sku = self.get_sku()
        mov_page = self.request.GET.get("page") or "1"
        stocks = (
            Stock.objects.filter(sku=sku)
            .select_related("warehouse", "bin")
            .order_by("warehouse__code")
        )
        movements = (
            StockMovement.objects.filter(sku=sku)
            .select_related("warehouse", "work_order")
            .order_by("-created_at")
        )
        pager = Paginator(movements, MOVEMENT_PAGE_SIZE)
        ctx.update(
            {
                "sku": sku,
                "stocks": stocks,
                "movements_page": pager.get_page(mov_page),
                "warehouses": Warehouse.objects.order_by("code"),
                "can_edit_warehouse": can_mutate_warehouse(self.request.user),
                "submit_token": uuid.uuid4().hex,
                "total_on_hand": sum((s.quantity or Decimal("0")) for s in stocks),
                "is_low": any(
                    (s.sku.reorder_level or 0) > 0 and s.quantity <= (s.sku.reorder_level or 0)
                    for s in stocks
                ),
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        require_permission(
            request.user,
            "warehouse.edit",
            message=_("Anbar əməliyyatı icazəniz yoxdur."),
        )
        if not can_mutate_warehouse(request.user):
            raise PermissionDenied(_("Anbar əməliyyatı icazəniz yoxdur."))
        sku = self.get_sku()
        action = request.POST.get("action")
        token = (request.POST.get("submit_token") or "").strip()
        session_key = f"wh_sku_{sku.pk}_{action}"
        if token and request.session.get(session_key) == token:
            messages.info(request, _("Bu forma artıq göndərilib."))
            return redirect("erp:warehouse_sku_detail", code=sku.code)
        try:
            if action == "update_sku":
                update_sku(
                    sku,
                    name=request.POST.get("name", ""),
                    unit=request.POST.get("unit") or "pcs",
                    reorder_level=request.POST.get("reorder_level") or "0",
                    actor=request.user,
                )
                messages.success(request, _("SKU yeniləndi."))
            elif action == "adjust_stock":
                warehouse = get_object_or_404(Warehouse, pk=request.POST.get("warehouse_id"))
                adjust_stock(
                    sku=sku,
                    warehouse=warehouse,
                    new_quantity=request.POST.get("quantity"),
                    reason=request.POST.get("reason", ""),
                    actor=request.user,
                )
                messages.success(request, _("Stok düzəldildi."))
            else:
                messages.error(request, _("Naməlum əməliyyat."))
        except (DomainError, ValueError) as exc:
            messages.error(request, str(exc))
            return redirect("erp:warehouse_sku_detail", code=sku.code)
        if token:
            request.session[session_key] = token
            request.session.modified = True
        return redirect("erp:warehouse_sku_detail", code=sku.code)


class WarehouseSkuCreateView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/warehouse_sku_form.html"
    permission_required = "warehouse.edit"
    permission_denied_message = "SKU yaratmaq icazəniz yoxdur."

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not can_mutate_warehouse(request.user):
            raise PermissionDenied(_("SKU yaratmaq icazəniz yoxdur."))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["mode"] = "create"
        ctx["submit_token"] = uuid.uuid4().hex
        return ctx

    def post(self, request, *args, **kwargs):
        if not can_mutate_warehouse(request.user):
            raise PermissionDenied(_("SKU yaratmaq icazəniz yoxdur."))
        token = (request.POST.get("submit_token") or "").strip()
        session_key = "wh_sku_create"
        if token and request.session.get(session_key) == token:
            last = request.session.get("wh_sku_create_code")
            if last:
                messages.info(request, _("Bu forma artıq göndərilib."))
                return redirect("erp:warehouse_sku_detail", code=last)
        try:
            sku = create_sku(
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                unit=request.POST.get("unit") or "pcs",
                reorder_level=request.POST.get("reorder_level") or "0",
                actor=request.user,
            )
        except DomainError as exc:
            messages.error(request, str(exc))
            return self.render_to_response(self.get_context_data())
        if token:
            request.session[session_key] = token
            request.session["wh_sku_create_code"] = sku.code
            request.session.modified = True
        messages.success(request, _("SKU yaradıldı: %(code)s") % {"code": sku.code})
        return redirect("erp:warehouse_sku_detail", code=sku.code)
