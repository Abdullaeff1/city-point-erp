"""Warehouse stocktake operator UI (Product Delivery Phase 8)."""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from apps.accounts.mixins import PermissionRequiredMixin, StaffRequiredMixin
from apps.core.services import DomainError
from apps.rbac.services import require_permission
from apps.warehouse.access import (
    can_count_stocktake,
    can_mutate_warehouse,
    can_post_stocktake_adjustments,
)
from apps.warehouse.models import SKU, Stock, Stocktake, StocktakeLine, StocktakeStatus, Warehouse
from apps.warehouse.stocktake import (
    add_found_sku,
    clear_line_count,
    complete_stocktake,
    mark_line_recount,
    parse_count_fields,
    post_stocktake_variances,
    refresh_activity_flags,
    save_line_count,
    start_stocktake,
    stocktake_progress,
)


class StocktakeListView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/stocktake_list.html"
    permission_required = "warehouse.view"
    permission_denied_message = "Anbara baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        warehouse_id = (self.request.GET.get("warehouse") or "").strip()
        qs = Stocktake.objects.select_related("warehouse", "started_by").order_by("-started_at")
        if warehouse_id.isdigit():
            qs = qs.filter(warehouse_id=int(warehouse_id))
        ctx.update(
            {
                "stocktakes": qs[:100],
                "warehouses": Warehouse.objects.order_by("code"),
                "warehouse_id": warehouse_id,
                "can_count": can_count_stocktake(self.request.user),
                "submit_token": uuid.uuid4().hex,
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        require_permission(
            request.user,
            "warehouse.edit",
            message=_("İnventar sayımı icazəniz yoxdur."),
        )
        if not can_count_stocktake(request.user):
            raise PermissionDenied(_("İnventar sayımı icazəniz yoxdur."))
        action = request.POST.get("action")
        token = (request.POST.get("submit_token") or "").strip()
        session_key = f"st_list_{action}"
        if token and request.session.get(session_key) == token:
            messages.info(request, _("Bu forma artıq göndərilib."))
            return redirect("erp:stocktake_list")
        try:
            if action == "start":
                warehouse = get_object_or_404(Warehouse, pk=request.POST.get("warehouse_id"))
                st = start_stocktake(
                    warehouse=warehouse,
                    actor=request.user,
                    notes=request.POST.get("notes") or "",
                )
                if token:
                    request.session[session_key] = token
                    request.session.modified = True
                messages.success(request, _("Sayım başladı: %(code)s") % {"code": st.code})
                return redirect("erp:stocktake_detail", code=st.code)
            messages.error(request, _("Naməlum əməliyyat."))
        except DomainError as exc:
            messages.error(request, str(exc))
        return redirect("erp:stocktake_list")


class StocktakeDetailView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/stocktake_detail.html"
    permission_required = "warehouse.view"
    permission_denied_message = "Anbara baxış icazəniz yoxdur."

    def get_stocktake(self):
        return get_object_or_404(
            Stocktake.objects.select_related("warehouse", "started_by", "completed_by", "posted_by"),
            code=self.kwargs["code"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        st = self.get_stocktake()
        if st.status in (StocktakeStatus.OPEN, StocktakeStatus.COMPLETED):
            refresh_activity_flags(st)
        lines = (
            st.lines.select_related("sku", "bin", "counted_by", "adjustment_movement")
            .order_by("sku__code")
        )
        filter_kind = (self.request.GET.get("filter") or "").strip()
        line_list = list(lines)
        if filter_kind == "uncounted":
            line_list = [ln for ln in line_list if ln.counted_qty is None]
        elif filter_kind == "diff":
            line_list = [
                ln
                for ln in line_list
                if ln.counted_qty is not None and ln.variance_qty is not None and ln.variance_qty != 0
            ]
        elif filter_kind == "recount":
            line_list = [ln for ln in line_list if ln.recount_required or ln.activity_after_count]
        # Live on-hand at render — snap field detects Case A stale saves.
        for ln in line_list:
            try:
                stock = Stock.objects.get(
                    sku_id=ln.sku_id, warehouse_id=st.warehouse_id, bin_id=ln.bin_id
                )
                ln.live_on_hand = stock.quantity or 0
            except Stock.DoesNotExist:
                ln.live_on_hand = 0
        progress = stocktake_progress(st)
        catalog_skus = SKU.objects.exclude(
            pk__in=st.lines.values_list("sku_id", flat=True)
        ).order_by("code")[:200]
        ctx.update(
            {
                "stocktake": st,
                "lines": line_list,
                "progress": progress,
                "filter_kind": filter_kind,
                "can_count": can_count_stocktake(self.request.user) and st.status == StocktakeStatus.OPEN,
                "can_complete": can_count_stocktake(self.request.user)
                and st.status == StocktakeStatus.OPEN,
                "can_post": can_post_stocktake_adjustments(self.request.user)
                and st.status == StocktakeStatus.COMPLETED,
                "can_edit_warehouse": can_mutate_warehouse(self.request.user),
                "catalog_skus": catalog_skus,
                "submit_token": uuid.uuid4().hex,
                "StocktakeStatus": StocktakeStatus,
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        st = self.get_stocktake()
        action = request.POST.get("action")
        token = (request.POST.get("submit_token") or "").strip()
        session_key = f"st_{st.pk}_{action}"
        if token and request.session.get(session_key) == token:
            messages.info(request, _("Bu forma artıq göndərilib."))
            return redirect("erp:stocktake_detail", code=st.code)

        try:
            if action == "save_counts":
                require_permission(
                    request.user,
                    "warehouse.edit",
                    message=_("Sayım daxil etmək icazəniz yoxdur."),
                )
                if not can_count_stocktake(request.user):
                    raise PermissionDenied(_("Sayım daxil etmək icazəniz yoxdur."))
                pairs = parse_count_fields(request.POST)
                saved = 0
                for line_id, raw, snap in pairs:
                    line = get_object_or_404(StocktakeLine, pk=line_id, stocktake=st)
                    save_line_count(
                        line=line,
                        counted_raw=raw,
                        actor=request.user,
                        displayed_on_hand=snap,
                    )
                    saved += 1
                messages.success(
                    request,
                    _("%(n)s sətir saxlanıldı.") % {"n": saved} if saved else _("Dəyişiklik yoxdur."),
                )
            elif action == "clear_line":
                require_permission(request.user, "warehouse.edit")
                if not can_count_stocktake(request.user):
                    raise PermissionDenied(_("Sayım silmək icazəniz yoxdur."))
                line = get_object_or_404(StocktakeLine, pk=request.POST.get("line_id"), stocktake=st)
                clear_line_count(line=line, actor=request.user)
                messages.info(request, _("Sətir sayılmamış kimi qeyd olundu."))
            elif action == "mark_recount":
                require_permission(request.user, "warehouse.edit")
                if not can_count_stocktake(request.user):
                    raise PermissionDenied(_("İcazə yoxdur."))
                line = get_object_or_404(StocktakeLine, pk=request.POST.get("line_id"), stocktake=st)
                mark_line_recount(line=line, actor=request.user, required=True)
                messages.info(request, _("Yenidən sayım işarələndi."))
            elif action == "clear_recount":
                require_permission(request.user, "warehouse.edit")
                if not can_count_stocktake(request.user):
                    raise PermissionDenied(_("İcazə yoxdur."))
                line = get_object_or_404(StocktakeLine, pk=request.POST.get("line_id"), stocktake=st)
                mark_line_recount(line=line, actor=request.user, required=False)
                messages.info(request, _("Yenidən sayım işarəsi silindi."))
            elif action == "add_sku":
                require_permission(request.user, "warehouse.edit")
                if not can_count_stocktake(request.user):
                    raise PermissionDenied(_("SKU əlavə etmək icazəniz yoxdur."))
                sku = get_object_or_404(SKU, pk=request.POST.get("sku_id"))
                add_found_sku(stocktake=st, sku=sku, actor=request.user)
                messages.success(request, _("SKU sayıma əlavə olundu: %(code)s") % {"code": sku.code})
            elif action == "complete":
                require_permission(request.user, "warehouse.edit")
                if not can_count_stocktake(request.user):
                    raise PermissionDenied(_("Sayımı bitirmək icazəniz yoxdur."))
                complete_stocktake(stocktake=st, actor=request.user)
                messages.success(request, _("Sayım bitirildi. Tarixi hesabat hazırdır."))
            elif action == "post_variances":
                require_permission(
                    request.user,
                    "warehouse.edit",
                    message=_("Stok düzəlişi icazəniz yoxdur."),
                )
                if not can_post_stocktake_adjustments(request.user):
                    raise PermissionDenied(_("Stok düzəlişi icazəniz yoxdur."))
                post_stocktake_variances(
                    stocktake=st,
                    actor=request.user,
                    reason=request.POST.get("reason") or "",
                )
                messages.success(request, _("Fərqlər tətbiq olundu."))
            else:
                messages.error(request, _("Naməlum əməliyyat."))
        except PermissionDenied:
            raise
        except DomainError as exc:
            messages.error(request, str(exc))
            return redirect("erp:stocktake_detail", code=st.code)

        if token:
            request.session[session_key] = token
            request.session.modified = True
        return redirect("erp:stocktake_detail", code=st.code)
