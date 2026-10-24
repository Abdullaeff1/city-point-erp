from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.mixins import RoleRequiredMixin
from apps.accounts.models import Role
from apps.billing.models import Charge
from apps.core.services import DomainError
from apps.maintenance.cost_import import (
    append_cost_rows,
    labeled_description,
    preview_key,
    read_cost_preview,
    sheet_template_response,
)
from apps.maintenance.costs import save_cost_sheet
from apps.maintenance.models import CostLineKind, WorkOrder, WorkOrderStatus
from apps.maintenance.services import WorkOrderService
from apps.procurement.services import ProcurementService
from apps.property.models import Contractor
from apps.tickets.access import tickets_visible_to
from apps.warehouse.models import SKU, Warehouse
from apps.warehouse.services import request_issue_line


def work_orders_for(user):
    visible_tickets = tickets_visible_to(user)
    return (
        WorkOrder.objects.filter(ticket__in=visible_tickets)
        .select_related("ticket", "ticket__company", "ticket__department", "space", "contractor")
        .order_by("-created_at")
    )


def procurement_mirror(wo):
    rows = []
    requests = wo.purchase_requests.prefetch_related("lines", "purchase_orders__lines").order_by("-created_at")
    for pr in requests:
        orders = list(pr.purchase_orders.all())
        po = orders[-1] if orders else None
        po_lines = list(po.lines.all()) if po else []
        pr_lines = list(pr.lines.all())
        for index, pr_line in enumerate(pr_lines):
            po_line = po_lines[index] if index < len(po_lines) else None
            unit_price = po_line.unit_price if po_line else None
            received = po_line.received_qty if po_line else None
            priced = bool(po_line and unit_price and unit_price > 0)
            qty_for_amount = None
            amount = None
            if priced:
                qty_for_amount = received if received and received > 0 else pr_line.qty
                amount = (qty_for_amount * unit_price).quantize(Decimal("0.01"))
            rows.append(
                {
                    "pr": pr,
                    "po": po,
                    "description": pr_line.description,
                    "requested_qty": pr_line.qty,
                    "unit_price": unit_price,
                    "received_qty": received,
                    "amount": amount,
                    "priced": priced,
                }
            )
    return rows


class WorkOrderListView(RoleRequiredMixin, TemplateView):
    template_name = "erp/work_orders.html"
    allowed_roles = (Role.SERVICE_DESK, Role.PROPERTY_FM)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["work_orders"] = work_orders_for(self.request.user)
        return ctx


class WorkOrderDetailView(RoleRequiredMixin, TemplateView):
    template_name = "erp/work_order_detail.html"
    allowed_roles = (Role.SERVICE_DESK, Role.PROPERTY_FM)

    def get_work_order(self):
        return get_object_or_404(work_orders_for(self.request.user), code=self.kwargs["code"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        wo = self.get_work_order()
        lines = list(wo.cost_lines.all())
        material = [line for line in lines if line.kind == CostLineKind.MATERIAL]
        labor = [line for line in lines if line.kind == CostLineKind.LABOR]
        material_total = sum((line.amount for line in material if line.unit_price and line.unit_price > 0), Decimal("0"))
        labor_total = sum((line.amount for line in labor if line.unit_price and line.unit_price > 0), Decimal("0"))
        ctx.update(
            {
                "wo": wo,
                "contractors": Contractor.objects.order_by("name"),
                "statuses": WorkOrderStatus.choices,
                "issues": wo.warehouse_issues.select_related("warehouse").prefetch_related("lines__sku"),
                "purchase_rows": procurement_mirror(wo),
                "charges": Charge.objects.filter(work_order=wo).order_by("-created_at"),
                "skus": SKU.objects.order_by("code"),
                "warehouses": Warehouse.objects.order_by("code"),
                "material_lines": material,
                "labor_lines": labor,
                "blank_rows": range(4),
                "material_total": material_total,
                "labor_total": labor_total,
                "formed_total": material_total + labor_total,
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        wo = self.get_work_order()
        action = request.POST.get("action")
        try:
            if action == "save":
                self._save_contractor(wo, request)
                messages.success(request, "İş sifarişi yeniləndi.")
            elif action == "sheet":
                save_cost_sheet(
                    wo,
                    material_rows=self._rows(request, "material"),
                    labor_rows=self._rows(request, "labor"),
                    resident_amount=self._optional_money(request.POST.get("resident_amount")),
                    billable=request.POST.get("billable") == "1",
                )
                messages.success(request, "Material və işçilik cədvəli saxlanıldı.")
            elif action in {"import_material", "import_labor"}:
                kind = CostLineKind.MATERIAL if action == "import_material" else CostLineKind.LABOR
                field = "material_file" if kind == CostLineKind.MATERIAL else "labor_file"
                upload = request.FILES.get(field)
                if upload is None:
                    raise DomainError("Fayl seçilməyib.")
                request.session[preview_key(wo.code)] = read_cost_preview(upload, default_kind=kind)
                request.session.modified = True
                return redirect("erp:work_order_import", code=wo.code)
            elif action == "status":
                WorkOrderService.set_status(wo, request.POST.get("status", ""), actor=request.user)
                messages.success(request, "Status yeniləndi.")
            elif action == "issue":
                self._request_issue(wo, request)
                messages.success(request, "Açıq çıxış sənədi yaradıldı. Anbar faktiki miqdarı təsdiqləyəcək.")
            elif action == "purchase":
                ProcurementService.create_pr_for_work_order(
                    wo,
                    actor=request.user,
                    description=request.POST.get("description", ""),
                    qty=request.POST.get("qty") or "1",
                )
                messages.success(request, "Satınalma tələbi iş sifarişinə bağlandı.")
        except (DomainError, ValueError) as exc:
            messages.error(request, str(exc))
        return redirect("erp:work_order_detail", code=wo.code)

    def _save_contractor(self, wo, request):
        contractor_id = request.POST.get("contractor") or None
        if contractor_id:
            contractor = Contractor.objects.filter(pk=contractor_id).first()
            if contractor is None:
                raise DomainError("Podratçı tapılmadı.")
            wo.contractor = contractor
        else:
            wo.contractor = None
        wo.save(update_fields=["contractor"])

    def _request_issue(self, wo, request):
        sku = SKU.objects.filter(pk=request.POST.get("sku") or None).first()
        warehouse = Warehouse.objects.filter(pk=request.POST.get("warehouse") or None).first()
        if sku is None or warehouse is None:
            raise DomainError("Məhsul və anbar seçilməlidir.")
        request_issue_line(
            work_order=wo,
            warehouse=warehouse,
            sku=sku,
            quantity=self._decimal(request.POST.get("quantity"), places=3),
            actor=request.user,
        )

    def _rows(self, request, prefix):
        ids = request.POST.getlist(f"{prefix}_id")
        descriptions = request.POST.getlist(f"{prefix}_description")
        qtys = request.POST.getlist(f"{prefix}_qty")
        units = request.POST.getlist(f"{prefix}_unit")
        prices = request.POST.getlist(f"{prefix}_price")
        count = max(len(ids), len(descriptions), len(qtys), len(units), len(prices))
        rows = []
        for index in range(count):
            rows.append(
                {
                    "id": (ids[index] if index < len(ids) else "").strip(),
                    "description": descriptions[index] if index < len(descriptions) else "",
                    "qty": self._decimal(qtys[index] if index < len(qtys) else "", places=3, blank_zero=True),
                    "unit": (units[index] if index < len(units) else "").strip()[:16],
                    "unit_price": self._money(
                        prices[index] if index < len(prices) else "",
                        blank_zero=True,
                    ),
                }
            )
        return rows

    @staticmethod
    def _decimal(raw, *, places, blank_zero=False):
        text = str(raw or "").strip().replace(" ", "")
        if text == "":
            if blank_zero:
                return Decimal("0")
            raise DomainError("Miqdar rəqəm olmalıdır.")
        text = text.replace(",", ".")
        try:
            value = Decimal(text)
        except InvalidOperation as exc:
            raise DomainError("Miqdar rəqəm olmalıdır.") from exc
        if value < 0:
            raise DomainError("Miqdar mənfi ola bilməz.")
        quant = Decimal("1").scaleb(-places)
        return value.quantize(quant)

    @classmethod
    def _money(cls, raw, *, blank_zero=False):
        return cls._decimal(raw, places=2, blank_zero=blank_zero)

    @classmethod
    def _optional_money(cls, raw):
        if str(raw or "").strip() == "":
            return None
        return cls._money(raw)


class WorkOrderImportView(RoleRequiredMixin, TemplateView):
    template_name = "erp/work_order_import.html"
    allowed_roles = (Role.SERVICE_DESK, Role.PROPERTY_FM)

    def _work_order(self):
        return get_object_or_404(work_orders_for(self.request.user), code=self.kwargs["code"])

    def _preview(self, code):
        return self.request.session.get(preview_key(code))

    def get(self, request, *args, **kwargs):
        wo = self._work_order()
        preview = self._preview(wo.code)
        if not preview:
            messages.error(request, "Yüklənmiş Excel yoxdur.")
            return redirect("erp:work_order_detail", code=wo.code)
        sheet_index = _sheet_index(request.GET.get("sheet"), preview)
        return self.render_to_response(self._context(wo, preview, sheet_index))

    def post(self, request, *args, **kwargs):
        wo = self._work_order()
        preview = self._preview(wo.code)
        if not preview:
            messages.error(request, "Yüklənmiş Excel yoxdur.")
            return redirect("erp:work_order_detail", code=wo.code)
        sheet_index = _sheet_index(request.POST.get("sheet"), preview)
        try:
            count = _confirm_preview(wo, preview["sheets"][sheet_index], request.POST)
        except DomainError as exc:
            messages.error(request, str(exc))
            return redirect(f"{request.path}?sheet={sheet_index}")
        request.session.pop(preview_key(wo.code), None)
        request.session.modified = True
        messages.success(request, f"{count} sətir əlavə olundu.")
        return redirect("erp:work_order_detail", code=wo.code)

    def _context(self, wo, preview, sheet_index):
        return {
            "wo": wo,
            "preview": preview,
            "sheet_index": sheet_index,
            "sheet": preview["sheets"][sheet_index],
            "kinds": (
                (CostLineKind.MATERIAL, "Material"),
                (CostLineKind.LABOR, "İşçilik"),
            ),
        }


def _sheet_index(raw, preview) -> int:
    try:
        index = int(raw or 0)
    except (TypeError, ValueError):
        index = 0
    count = len(preview.get("sheets") or [])
    if count == 0 or index < 0 or index >= count:
        return 0
    return index


def _confirm_preview(wo, sheet, posted) -> int:
    selected = set(posted.getlist("use"))
    grouped = {CostLineKind.MATERIAL: [], CostLineKind.LABOR: []}
    for block_index, block in enumerate(sheet.get("blocks") or []):
        kind = posted.get(f"kind-{block_index}") or block.get("kind")
        if kind not in {CostLineKind.MATERIAL, CostLineKind.LABOR}:
            raise DomainError("Naməlum cədvəl.")
        for row_index, row in enumerate(block.get("rows") or []):
            if f"{block_index}:{row_index}" not in selected:
                continue
            grouped[kind].append(
                {
                    "description": labeled_description(block, row),
                    "qty": row["qty"],
                    "unit": row["unit"],
                    "unit_price": row["unit_price"],
                }
            )
    count = sum(len(rows) for rows in grouped.values())
    if count == 0:
        raise DomainError("Seçilmiş sətir yoxdur.")
    for kind, rows in grouped.items():
        if rows:
            append_cost_rows(wo, kind=kind, rows=rows)
    return count


class WorkOrderSheetTemplateView(RoleRequiredMixin, View):
    allowed_roles = (Role.SERVICE_DESK, Role.PROPERTY_FM)

    def get(self, request, code):
        get_object_or_404(work_orders_for(request.user), code=code)
        kind = request.GET.get("kind") or CostLineKind.MATERIAL
        try:
            return sheet_template_response(kind)
        except DomainError as exc:
            messages.error(request, str(exc))
            return redirect("erp:work_order_detail", code=code)
