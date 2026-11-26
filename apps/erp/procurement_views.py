"""Procurement operator UI — PR / Supplier / PO / RFQ (Phase 4.4.2.3)."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from apps.accounts.mixins import PermissionRequiredMixin, StaffRequiredMixin
from apps.core.services import DomainError
from apps.rbac.services import require_permission, user_has_permission
from apps.procurement.models import (
    ComparisonCoverage,
    POLine,
    POStatus,
    PRLineAward,
    PRSource,
    PRStatus,
    PurchaseOrder,
    PurchaseRequest,
    QuoteLineResponseStatus,
    RFQ,
    RFQDispatchChannel,
    RFQInvitation,
    RFQQuote,
)
from apps.procurement.services import ProcurementService
from apps.parties.models import Party, PartyStatus
from apps.warehouse.models import SKU, Warehouse


PAGE_SIZE = 40


def _can_edit(user) -> bool:
    from apps.accounts.models import Role

    if getattr(user, "role", None) == Role.MANAGEMENT:
        return False
    return user_has_permission(user, "procurement.edit")


def _can_approve(user) -> bool:
    return user_has_permission(user, "procurement.approve")


def _pr_allows_po(pr: PurchaseRequest) -> bool:
    """Service allows PO/RFQ quote→PO while PR is approved or already ordered."""
    return pr.status in {PRStatus.APPROVED, PRStatus.ORDERED}


def _pending_commitments_for_pr(pr: PurchaseRequest):
    from django.contrib.contenttypes.models import ContentType

    from apps.procurement.services import WF_PROCUREMENT_COMMITMENT
    from apps.workflows.models import ApprovalRequest, ApprovalStatus

    ct = ContentType.objects.get_for_model(PurchaseRequest)
    return list(
        ApprovalRequest.objects.filter(
            workflow_code=WF_PROCUREMENT_COMMITMENT,
            status=ApprovalStatus.PENDING,
            entity_type=ct,
            entity_id=pr.pk,
        ).order_by("-id")[:5]
    )


class ProcurementListView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/procurement.html"
    permission_required = "procurement.view"
    permission_denied_message = "Satınalmaya baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        request = self.request
        q = (request.GET.get("q") or "").strip()
        source = (request.GET.get("source") or "").strip()
        status = (request.GET.get("status") or "").strip()
        po_status = (request.GET.get("po_status") or "").strip()
        # Legacy dashboard links used ?status=partial for POs — map known PO statuses.
        if not po_status and status in {c.value for c in POStatus}:
            po_status = status
            if status not in {c.value for c in PRStatus}:
                status = ""
        pr_page = request.GET.get("pr_page") or "1"
        po_page = request.GET.get("po_page") or "1"

        pr_qs = PurchaseRequest.objects.select_related("work_order", "requested_by").prefetch_related(
            "lines"
        )
        po_qs = (
            PurchaseOrder.objects.select_related("supplier_party", "pr")
            .prefetch_related("lines")
            .order_by("-id")
        )
        pr_qs = pr_qs.order_by("-created_at", "-id")
        if q:
            pr_qs = pr_qs.filter(Q(code__icontains=q) | Q(title__icontains=q) | Q(notes__icontains=q))
            po_qs = po_qs.filter(
                Q(code__icontains=q)
                | Q(supplier_party__legal_name__icontains=q)
                | Q(pr__code__icontains=q)
            )
        if source in {c.value for c in PRSource}:
            pr_qs = pr_qs.filter(source=source)
        if status in {c.value for c in PRStatus}:
            pr_qs = pr_qs.filter(status=status)
        if po_status in {c.value for c in POStatus}:
            po_qs = po_qs.filter(status=po_status)

        ctx.update(
            {
                "q": q,
                "source": source,
                "status": status,
                "po_status": po_status,
                "prs_page": Paginator(pr_qs, PAGE_SIZE).get_page(pr_page),
                "pos_page": Paginator(po_qs, PAGE_SIZE).get_page(po_page),
                "warehouses": Warehouse.objects.order_by("code"),
                "suppliers": ProcurementService.supplier_queryset().filter(status=PartyStatus.ACTIVE),
                "skus": SKU.objects.order_by("code")[:300],
                "can_edit_procurement": _can_edit(request.user),
                "can_approve_procurement": _can_approve(request.user),
                "pr_sources": PRSource.choices,
                "pr_statuses": PRStatus.choices,
                "submit_token": uuid.uuid4().hex,
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        from apps.maintenance.costs import sync_procurement_cost

        action = request.POST.get("action")
        token = (request.POST.get("submit_token") or "").strip()
        session_key = f"proc_{action}"
        # Durable receipt idempotency is handled by operation_key in the service layer.
        if action != "receive_po" and token and request.session.get(session_key) == token:
            messages.info(request, _("Bu forma artıq göndərilib."))
            return redirect("erp:procurement")

        try:
            if action == "approve_pr":
                require_permission(
                    request.user, "procurement.approve", message=_("Satınalma təsdiqi icazəniz yoxdur.")
                )
                pr = get_object_or_404(PurchaseRequest, pk=request.POST.get("pr_id"))
                ProcurementService.approve_pr(pr, actor=request.user)
                messages.success(request, _("%(code)s təsdiqləndi") % {"code": pr.code})
            elif action == "create_po":
                require_permission(
                    request.user, "procurement.edit", message=_("PO yaratmaq icazəniz yoxdur.")
                )
                pr = get_object_or_404(PurchaseRequest, pk=request.POST.get("pr_id"))
                supplier = get_object_or_404(Party, pk=request.POST.get("supplier_party_id"))
                po = ProcurementService.create_po_from_pr(
                    pr, supplier_party=supplier, actor=request.user
                )
                messages.success(request, _("PO: %(code)s") % {"code": po.code})
            elif action == "set_line_price":
                require_permission(
                    request.user,
                    "procurement.edit",
                    message=_("Satınalma qiyməti dəyişmək icazəniz yoxdur."),
                )
                line = get_object_or_404(
                    POLine.objects.select_related("po__pr"), pk=request.POST.get("line_id")
                )
                raw = str(request.POST.get("unit_price") or "0").strip().replace(" ", "").replace(",", ".")
                try:
                    price = Decimal(raw)
                except InvalidOperation:
                    messages.error(request, _("Qiymət rəqəm olmalıdır."))
                    return redirect("erp:procurement")
                ProcurementService.set_po_line_unit_price(
                    line, unit_price=price, actor=request.user
                )
                if line.po.pr_id and line.po.pr.work_order_id:
                    sync_procurement_cost(line.po.pr.work_order)
                messages.success(request, _("Satınalma qiyməti saxlanıldı."))
            elif action == "receive_po":
                require_permission(
                    request.user, "procurement.edit", message=_("PO qəbulu icazəniz yoxdur.")
                )
                po = get_object_or_404(PurchaseOrder, pk=request.POST.get("po_id"))
                wh = Warehouse.objects.filter(pk=request.POST.get("warehouse_id") or None).first()
                if wh is None:
                    wh = Warehouse.objects.first()
                if not wh:
                    messages.error(request, _("Anbar yoxdur"))
                else:
                    receive_mode = (request.POST.get("receive_mode") or "full").strip().lower()
                    operation_key = (request.POST.get("operation_key") or "").strip() or uuid.uuid4().hex
                    line_qtys = {}
                    for line in po.lines.all():
                        raw = request.POST.get(f"recv_qty_{line.pk}")
                        if raw is not None and str(raw).strip() != "":
                            line_qtys[line.pk] = str(raw).replace(",", ".")
                    if receive_mode == "partial":
                        result = ProcurementService.receive_po(
                            po,
                            warehouse=wh,
                            actor=request.user,
                            line_qtys=line_qtys,
                            operation_key=operation_key,
                            receive_mode="partial",
                        )
                    else:
                        result = ProcurementService.receive_po(
                            po,
                            warehouse=wh,
                            actor=request.user,
                            line_qtys=None,
                            operation_key=operation_key,
                            receive_mode="full",
                        )
                    result.refresh_from_db()
                    if getattr(result, "receipt_replayed", False):
                        messages.info(request, _("Bu qəbul artıq qeydə alınıb."))
                    else:
                        messages.success(
                            request,
                            _("%(code)s qəbul edildi (%(status)s)")
                            % {"code": result.code, "status": result.status},
                        )
            elif action == "create_rfq":
                require_permission(
                    request.user, "procurement.edit", message=_("RFQ yaratmaq icazəniz yoxdur.")
                )
                pr = get_object_or_404(PurchaseRequest, pk=request.POST.get("pr_id"))
                rfq = ProcurementService.create_rfq_from_pr(pr, actor=request.user)
                messages.success(request, _("RFQ: %(code)s") % {"code": rfq.code})
                if token:
                    request.session[session_key] = token
                    request.session.modified = True
                return redirect("erp:procurement_rfq_detail", code=rfq.code)
            else:
                messages.error(request, _("Naməlum əməliyyat."))
        except DomainError as exc:
            messages.info(request, str(exc))
        except (ValueError, PermissionDenied) as exc:
            messages.error(request, str(exc))

        if token:
            request.session[session_key] = token
            request.session.modified = True
        return redirect("erp:procurement")


class ProcurementPRCreateView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/procurement_pr_form.html"
    permission_required = "procurement.edit"
    permission_denied_message = "Satınalma sorğusu yaratmaq icazəniz yoxdur."

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not _can_edit(request.user):
            raise PermissionDenied(_("Satınalma sorğusu yaratmaq icazəniz yoxdur."))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["skus"] = SKU.objects.order_by("code")[:500]
        ctx["submit_token"] = uuid.uuid4().hex
        ctx["line_range"] = range(5)
        return ctx

    def post(self, request, *args, **kwargs):
        if not _can_edit(request.user):
            raise PermissionDenied(_("Satınalma sorğusu yaratmaq icazəniz yoxdur."))
        token = (request.POST.get("submit_token") or "").strip()
        if token and request.session.get("proc_manual_pr") == token:
            last = request.session.get("proc_manual_pr_code")
            if last:
                messages.info(request, _("Bu forma artıq göndərilib."))
                return redirect("erp:procurement_pr_detail", code=last)
        # Ignore any posted source — server assigns MANUAL.
        lines = []
        for i in range(12):
            desc = request.POST.get(f"line_description_{i}", "")
            qty = request.POST.get(f"line_qty_{i}", "")
            unit = request.POST.get(f"line_unit_{i}", "pcs")
            sku_id = request.POST.get(f"line_sku_{i}") or None
            if not str(desc).strip() and not sku_id and not str(qty).strip():
                continue
            lines.append(
                {"description": desc, "qty": qty or "0", "unit": unit, "sku_id": sku_id}
            )
        try:
            pr = ProcurementService.create_manual_pr(
                actor=request.user,
                title=request.POST.get("title", ""),
                notes=request.POST.get("notes", ""),
                lines=lines,
            )
        except DomainError as exc:
            messages.error(request, str(exc))
            return self.render_to_response(self.get_context_data())
        if token:
            request.session["proc_manual_pr"] = token
            request.session["proc_manual_pr_code"] = pr.code
            request.session.modified = True
        messages.success(request, _("PR yaradıldı: %(code)s") % {"code": pr.code})
        return redirect("erp:procurement_pr_detail", code=pr.code)


class ProcurementPRDetailView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/procurement_pr_detail.html"
    permission_required = "procurement.view"
    permission_denied_message = "Satınalmaya baxış icazəniz yoxdur."

    def get_pr(self):
        return get_object_or_404(
            PurchaseRequest.objects.select_related("work_order", "requested_by").prefetch_related(
                "lines__sku", "rfqs", "purchase_orders__supplier_party"
            ),
            code=self.kwargs["code"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        pr = self.get_pr()
        qty_progress = ProcurementService.pr_qty_progress(pr)
        has_remaining = any(row["outstanding_order"] > 0 for row in qty_progress)
        ctx.update(
            {
                "pr": pr,
                "qty_progress": qty_progress,
                "can_edit_procurement": _can_edit(self.request.user),
                "can_approve_procurement": _can_approve(self.request.user),
                "can_issue_po": _can_edit(self.request.user)
                and _pr_allows_po(pr)
                and has_remaining,
                "pending_commitments": _pending_commitments_for_pr(pr),
                "suppliers": ProcurementService.supplier_queryset().filter(status=PartyStatus.ACTIVE),
                "submit_token": uuid.uuid4().hex,
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        pr = self.get_pr()
        action = request.POST.get("action")
        try:
            if action == "approve_pr":
                require_permission(
                    request.user, "procurement.approve", message=_("Satınalma təsdiqi icazəniz yoxdur.")
                )
                ProcurementService.approve_pr(pr, actor=request.user)
                messages.success(request, _("Təsdiqləndi."))
            elif action == "create_po":
                require_permission(
                    request.user, "procurement.edit", message=_("PO yaratmaq icazəniz yoxdur.")
                )
                supplier = get_object_or_404(Party, pk=request.POST.get("supplier_party_id"))
                po = ProcurementService.create_po_from_pr(
                    pr, supplier_party=supplier, actor=request.user
                )
                messages.success(request, _("PO: %(code)s") % {"code": po.code})
                return redirect("erp:procurement_po_detail", code=po.code)
            elif action == "create_rfq":
                require_permission(
                    request.user, "procurement.edit", message=_("RFQ yaratmaq icazəniz yoxdur.")
                )
                rfq = ProcurementService.create_rfq_from_pr(pr, actor=request.user)
                return redirect("erp:procurement_rfq_detail", code=rfq.code)
            else:
                messages.error(request, _("Naməlum əməliyyat."))
        except DomainError as exc:
            messages.info(request, str(exc))
        return redirect("erp:procurement_pr_detail", code=pr.code)


class ProcurementPODetailView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/procurement_po_detail.html"
    permission_required = "procurement.view"
    permission_denied_message = "Satınalmaya baxış icazəniz yoxdur."

    def get_po(self):
        return get_object_or_404(
            PurchaseOrder.objects.select_related("supplier_party", "pr").prefetch_related("lines__sku"),
            code=self.kwargs["code"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        po = self.get_po()
        ctx.update(
            {
                "po": po,
                "warehouses": Warehouse.objects.order_by("code"),
                "can_edit_procurement": _can_edit(self.request.user),
                "submit_token": uuid.uuid4().hex,
                "operation_key": uuid.uuid4().hex,
                "can_receive": po.status in {POStatus.SENT, POStatus.PARTIAL},
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        from apps.maintenance.costs import sync_procurement_cost

        po = self.get_po()
        action = request.POST.get("action")
        try:
            if action == "set_line_price":
                require_permission(
                    request.user, "procurement.edit", message=_("Qiymət dəyişmək icazəniz yoxdur.")
                )
                line = get_object_or_404(po.lines.all(), pk=request.POST.get("line_id"))
                raw = str(request.POST.get("unit_price") or "0").strip().replace(",", ".")
                price = Decimal(raw)
                ProcurementService.set_po_line_unit_price(
                    line, unit_price=price, actor=request.user
                )
                if po.pr_id and po.pr.work_order_id:
                    sync_procurement_cost(po.pr.work_order)
                messages.success(request, _("Qiymət saxlanıldı."))
            elif action == "receive_po":
                require_permission(
                    request.user, "procurement.edit", message=_("PO qəbulu icazəniz yoxdur.")
                )
                wh = Warehouse.objects.filter(pk=request.POST.get("warehouse_id") or None).first()
                if not wh:
                    raise DomainError(_("Anbar seçilməlidir."))
                receive_mode = (request.POST.get("receive_mode") or "partial").strip().lower()
                operation_key = (request.POST.get("operation_key") or "").strip() or uuid.uuid4().hex
                line_qtys = {}
                for line in po.lines.all():
                    raw = request.POST.get(f"recv_qty_{line.pk}")
                    if raw is not None and str(raw).strip() != "":
                        line_qtys[line.pk] = str(raw).replace(",", ".")
                if receive_mode == "full":
                    result = ProcurementService.receive_po(
                        po,
                        warehouse=wh,
                        actor=request.user,
                        line_qtys=None,
                        operation_key=operation_key,
                        receive_mode="full",
                    )
                else:
                    result = ProcurementService.receive_po(
                        po,
                        warehouse=wh,
                        actor=request.user,
                        line_qtys=line_qtys,
                        operation_key=operation_key,
                        receive_mode="partial",
                    )
                if getattr(result, "receipt_replayed", False):
                    messages.info(request, _("Bu qəbul artıq qeydə alınıb."))
                else:
                    messages.success(request, _("Qəbul edildi."))
            else:
                messages.error(request, _("Naməlum əməliyyat."))
        except (DomainError, ValueError, InvalidOperation) as exc:
            messages.error(request, str(exc))
        return redirect("erp:procurement_po_detail", code=po.code)


class ProcurementSupplierListView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/procurement_suppliers.html"
    permission_required = "procurement.view"
    permission_denied_message = "Satınalmaya baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q = (self.request.GET.get("q") or "").strip()
        qs = ProcurementService.supplier_queryset()
        if q:
            qs = qs.filter(
                Q(legal_name__icontains=q)
                | Q(brand_name__icontains=q)
                | Q(tax_id__icontains=q)
                | Q(contact_email__icontains=q)
            )
        status = (self.request.GET.get("status") or "").strip()
        if status in {c.value for c in PartyStatus}:
            qs = qs.filter(status=status)
        page = Paginator(qs, PAGE_SIZE).get_page(self.request.GET.get("page") or "1")
        ctx.update(
            {
                "q": q,
                "status": status,
                "suppliers_page": page,
                "can_edit_procurement": _can_edit(self.request.user),
                "statuses": PartyStatus.choices,
            }
        )
        return ctx


class ProcurementSupplierFormView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/procurement_supplier_form.html"
    permission_required = "procurement.edit"
    permission_denied_message = "Podratçı idarəetməsi icazəniz yoxdur."

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not _can_edit(request.user):
            raise PermissionDenied(_("Podratçı idarəetməsi icazəniz yoxdur."))
        return super().dispatch(request, *args, **kwargs)

    def get_party(self):
        pk = self.kwargs.get("pk")
        if not pk:
            return None
        return get_object_or_404(ProcurementService.supplier_queryset(), pk=pk)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        party = self.get_party()
        ctx.update(
            {
                "party": party,
                "mode": "edit" if party else "create",
                "statuses": PartyStatus.choices,
                "submit_token": uuid.uuid4().hex,
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        party = self.get_party()
        token = (request.POST.get("submit_token") or "").strip()
        session_key = f"proc_supplier_{party.pk if party else 'new'}"
        if token and request.session.get(session_key) == token:
            messages.info(request, _("Bu forma artıq göndərilib."))
            if party:
                return redirect("erp:procurement_supplier_detail", pk=party.pk)
            return redirect("erp:procurement_suppliers")
        try:
            party = ProcurementService.create_or_update_supplier(
                actor=request.user,
                party=party,
                legal_name=request.POST.get("legal_name", ""),
                brand_name=request.POST.get("brand_name", ""),
                tax_id=request.POST.get("tax_id", ""),
                contact_email=request.POST.get("contact_email", ""),
                contact_phone=request.POST.get("contact_phone", ""),
                notes=request.POST.get("notes", ""),
                status=request.POST.get("status") or PartyStatus.ACTIVE,
            )
        except DomainError as exc:
            messages.error(request, str(exc))
            return self.render_to_response(self.get_context_data())
        if token:
            request.session[session_key] = token
            request.session.modified = True
        messages.success(request, _("Podratçı saxlanıldı."))
        return redirect("erp:procurement_supplier_detail", pk=party.pk)


class ProcurementSupplierDetailView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/procurement_supplier_detail.html"
    permission_required = "procurement.view"
    permission_denied_message = "Satınalmaya baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        party = get_object_or_404(ProcurementService.supplier_queryset(), pk=self.kwargs["pk"])
        pos = PurchaseOrder.objects.filter(supplier_party=party).select_related("pr").order_by("-id")[:50]
        ctx.update(
            {
                "party": party,
                "purchase_orders": pos,
                "can_edit_procurement": _can_edit(self.request.user),
            }
        )
        return ctx


class ProcurementRFQDetailView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/procurement_rfq_detail.html"
    permission_required = "procurement.view"
    permission_denied_message = "Satınalmaya baxış icazəniz yoxdur."

    def get_rfq(self):
        return get_object_or_404(
            RFQ.objects.select_related("pr").prefetch_related(
                "quotes__supplier_party",
                "quotes__lines",
                "invitations__supplier_party",
                "invitations__lines",
            ),
            code=self.kwargs["code"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        rfq = self.get_rfq()
        quotes = list(rfq.quotes.select_related("supplier_party").order_by("unit_price", "id"))
        pr_lines = list(rfq.pr.lines.select_related("sku").order_by("id")) if rfq.pr_id else []
        qty_progress = ProcurementService.pr_qty_progress(rfq.pr) if rfq.pr_id else []
        remaining_total_qty = sum(
            (row["outstanding_order"] for row in qty_progress), Decimal("0")
        )
        header_quotes = [q for q in quotes if not q.lines.exists()]
        quote_rows = []
        comparable = []
        historical = []
        for q in header_quotes:
            assessed = (
                ProcurementService.assess_quote_amount(q, rfq.pr)
                if rfq.pr_id
                else None
            )
            complete = bool(assessed and assessed.is_known and assessed.reason == "ok")
            row = {
                "quote": q,
                "assessed": assessed,
                "complete": complete,
                "covers_all_pr_lines": bool(pr_lines) and complete,
            }
            quote_rows.append(row)
            if complete:
                comparable.append(row)
            # After remaining qty is fully ordered, still rank header quotes historically
            if (q.currency or "AZN").upper() == "AZN":
                historical.append(row)
        lowest_id = None
        if comparable:
            comparable.sort(
                key=lambda r: (r["assessed"].amount, r["quote"].pk)
            )
            lowest_id = comparable[0]["quote"].pk
        elif historical:
            historical.sort(
                key=lambda r: (Decimal(str(r["quote"].unit_price or 0)), r["quote"].pk)
            )
            lowest_id = historical[0]["quote"].pk

        comparison_raw = (
            ProcurementService.build_line_comparison(rfq)
            if rfq.pr_id
            else {"rows": [], "suppliers": []}
        )
        comparison_suppliers = comparison_raw.get("suppliers") or []
        comparison_rows = []
        for row in comparison_raw.get("rows") or []:
            cells_ordered = []
            for s in comparison_suppliers:
                cell = row.cells.get(s["id"])
                cells_ordered.append({"supplier_id": s["id"], "cell": cell})
            comparison_rows.append(
                {
                    "pr_line": row.pr_line,
                    "remaining_qty": row.remaining_qty,
                    "cells_ordered": cells_ordered,
                }
            )
        comparison = {"rows": comparison_rows, "suppliers": comparison_suppliers}
        active_awards = []
        if rfq.pr_id:
            active_awards = list(
                PRLineAward.objects.filter(pr=rfq.pr, is_active=True)
                .select_related("pr_line", "supplier_party", "quote_line", "po_line")
                .order_by("pr_line_id")
            )
        invitations = list(
            RFQInvitation.objects.filter(rfq=rfq)
            .select_related("supplier_party")
            .prefetch_related("lines__pr_line")
            .order_by("-is_active", "-created_at")
        )
        has_unissued_awards = any(a.po_line_id is None for a in active_awards)
        can_select = (
            _can_edit(self.request.user)
            and rfq.pr_id is not None
            and _pr_allows_po(rfq.pr)
            and remaining_total_qty > 0
            and not has_unissued_awards
        )
        can_award = (
            _can_edit(self.request.user)
            and rfq.pr_id is not None
            and _pr_allows_po(rfq.pr)
            and remaining_total_qty > 0
        )
        po_outcomes = self.request.session.pop(f"rfq_po_outcomes_{rfq.code}", None)
        ctx.update(
            {
                "rfq": rfq,
                "quotes": quotes,
                "quote_rows": quote_rows,
                "pr_lines": pr_lines,
                "qty_progress": qty_progress,
                "remaining_total_qty": remaining_total_qty,
                "lowest_quote_id": lowest_id,
                "suppliers": ProcurementService.supplier_queryset().filter(
                    status=PartyStatus.ACTIVE
                ),
                "can_edit_procurement": _can_edit(self.request.user),
                "can_select_quote": can_select,
                "can_award_lines": can_award,
                "pending_commitments": (
                    _pending_commitments_for_pr(rfq.pr) if rfq.pr_id else []
                ),
                "line_comparison": comparison,
                "invitations": invitations,
                "active_awards": active_awards,
                "has_unissued_awards": has_unissued_awards,
                "po_outcomes": po_outcomes,
                "dispatch_channels": RFQDispatchChannel.choices,
                "coverage_labels": {
                    ComparisonCoverage.NOT_INVITED: _("Dəvət olunmayıb"),
                    ComparisonCoverage.INVITED_UNANSWERED: _("Cavabsız"),
                    ComparisonCoverage.QUOTED: _("Təklif edilib"),
                },
                "submit_token": uuid.uuid4().hex,
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        rfq = self.get_rfq()
        action = request.POST.get("action")
        try:
            if action == "add_quote":
                require_permission(
                    request.user, "procurement.edit", message=_("Təklif əlavə etmək icazəniz yoxdur.")
                )
                supplier = get_object_or_404(Party, pk=request.POST.get("supplier_party_id"))
                ProcurementService.add_rfq_quote(
                    rfq,
                    supplier_party=supplier,
                    unit_price=request.POST.get("unit_price"),
                    lead_time_days=request.POST.get("lead_time_days") or 0,
                    notes=request.POST.get("notes", ""),
                    actor=request.user,
                )
                messages.success(request, _("Təklif əlavə olundu."))
            elif action == "select_quote":
                require_permission(
                    request.user, "procurement.edit", message=_("PO yaratmaq icazəniz yoxdur.")
                )
                quote = get_object_or_404(RFQQuote, pk=request.POST.get("quote_id"), rfq=rfq)
                po = ProcurementService.select_rfq_quote_and_create_po(quote, actor=request.user)
                messages.success(request, _("PO yaradıldı: %(code)s") % {"code": po.code})
                return redirect("erp:procurement_po_detail", code=po.code)
            elif action == "invite_supplier":
                require_permission(
                    request.user, "procurement.edit", message=_("Dəvət icazəniz yoxdur.")
                )
                supplier = get_object_or_404(Party, pk=request.POST.get("supplier_party_id"))
                line_ids = request.POST.getlist("invite_line_id")
                line_specs = []
                for lid in line_ids:
                    qty_raw = request.POST.get(f"invite_qty_{lid}", "").strip()
                    spec = {"pr_line_id": int(lid)}
                    if qty_raw:
                        spec["qty"] = qty_raw
                    line_specs.append(spec)
                channel = request.POST.get("dispatch_channel") or RFQDispatchChannel.DRAFT
                dispatch_ref = (request.POST.get("dispatch_ref") or "").strip()
                mark = request.POST.get("mark_dispatched") == "1"
                inv = ProcurementService.invite_supplier_to_rfq(
                    rfq,
                    supplier_party=supplier,
                    line_specs=line_specs,
                    actor=request.user,
                    dispatch_channel=channel,
                    dispatch_ref=dispatch_ref,
                    mark_dispatched=mark,
                )
                messages.success(
                    request,
                    _("Dəvət yaradıldı (#%(id)s)%(disp)s")
                    % {
                        "id": inv.pk,
                        "disp": _(" · göndərilib") if inv.is_dispatched else "",
                    },
                )
            elif action == "add_line_quote":
                require_permission(
                    request.user, "procurement.edit", message=_("Təklif əlavə etmək icazəniz yoxdur.")
                )
                supplier = get_object_or_404(Party, pk=request.POST.get("supplier_party_id"))
                line_ids = request.POST.getlist("quote_line_id")
                responses = []
                for lid in line_ids:
                    status = (
                        request.POST.get(f"response_status_{lid}")
                        or QuoteLineResponseStatus.QUOTED
                    )
                    resp = {"pr_line_id": int(lid), "response_status": status}
                    if status == QuoteLineResponseStatus.QUOTED:
                        resp["unit_price"] = request.POST.get(f"unit_price_{lid}", "")
                        qty = request.POST.get(f"qty_{lid}", "").strip()
                        if qty:
                            resp["qty"] = qty
                        vat = request.POST.get(f"vat_rate_{lid}", "").strip()
                        if vat:
                            resp["vat_rate"] = vat
                        resp["price_includes_vat"] = (
                            request.POST.get(f"price_includes_vat_{lid}") == "1"
                        )
                    responses.append(resp)
                ProcurementService.add_rfq_quote_lines(
                    rfq,
                    supplier_party=supplier,
                    line_responses=responses,
                    actor=request.user,
                    supplier_reference=request.POST.get("supplier_reference", ""),
                    notes=request.POST.get("notes", ""),
                    lead_time_days=request.POST.get("lead_time_days") or 0,
                )
                messages.success(request, _("Sətir təklifi əlavə olundu."))
            elif action == "award_lines":
                require_permission(
                    request.user, "procurement.edit", message=_("Mükafat icazəniz yoxdur.")
                )
                if not rfq.pr_id:
                    raise DomainError(_("RFQ PR-ə bağlı deyil."))
                pairs = request.POST.getlist("award_pair")
                selections = []
                for pair in pairs:
                    # format: pr_line_id:quote_line_id
                    parts = str(pair).split(":")
                    if len(parts) != 2:
                        continue
                    selections.append(
                        {"pr_line_id": int(parts[0]), "quote_line_id": int(parts[1])}
                    )
                awards = ProcurementService.award_pr_lines(
                    rfq.pr,
                    selections,
                    actor=request.user,
                    reason=request.POST.get("award_reason", ""),
                )
                messages.success(
                    request, _("Mükafatlandı: %(n)s sətir") % {"n": len(awards)}
                )
            elif action == "create_pos_from_awards":
                require_permission(
                    request.user, "procurement.edit", message=_("PO yaratmaq icazəniz yoxdur.")
                )
                if not rfq.pr_id:
                    raise DomainError(_("RFQ PR-ə bağlı deyil."))
                outcomes = ProcurementService.create_pos_from_awards(
                    rfq.pr, actor=request.user
                )
                serializable = []
                for o in outcomes:
                    serializable.append(
                        {
                            "supplier_id": o.supplier_id,
                            "supplier_name": o.supplier_name,
                            "status": o.status,
                            "message": o.message,
                            "po_code": o.po.code if o.po else "",
                        }
                    )
                    if o.status == "issued" and o.po:
                        messages.success(
                            request,
                            _("%(sup)s: PO %(code)s")
                            % {"sup": o.supplier_name, "code": o.po.code},
                        )
                    elif o.status == "awaiting_financial_approval":
                        messages.info(
                            request,
                            _("%(sup)s: maliyyə təsdiqi gözlənilir — %(msg)s")
                            % {"sup": o.supplier_name, "msg": o.message},
                        )
                    elif o.status == "failed":
                        messages.error(
                            request,
                            _("%(sup)s: %(msg)s")
                            % {"sup": o.supplier_name or "—", "msg": o.message},
                        )
                request.session[f"rfq_po_outcomes_{rfq.code}"] = serializable
            else:
                messages.error(request, _("Naməlum əməliyyat."))
        except DomainError as exc:
            messages.info(request, str(exc))
        return redirect("erp:procurement_rfq_detail", code=rfq.code)


def _annotate_procurement_approval_links(rows):
    """Attach PR/RFQ deep links for Supply RO / ready queues (no decide actions)."""
    from apps.procurement.models import RFQQuote
    from apps.procurement.services import WF_PROCUREMENT_COMMITMENT, WF_PROCUREMENT_PR

    for req in rows:
        payload = req.payload or {}
        code = payload.get("code") or ""
        req.view_url = (
            reverse("erp:procurement_pr_detail", kwargs={"code": code})
            if code
            else reverse("erp:procurement")
        )
        req.view_label = _("PR-ə bax")
        req.kind_label = (
            _("Satınalma öhdəlik")
            if req.workflow_code == WF_PROCUREMENT_COMMITMENT
            else _("Satınalma PR")
        )
        if req.workflow_code == WF_PROCUREMENT_COMMITMENT and payload.get("quote_id"):
            quote = (
                RFQQuote.objects.select_related("rfq")
                .filter(pk=payload.get("quote_id"))
                .first()
            )
            if quote and quote.rfq_id:
                req.view_url = reverse(
                    "erp:procurement_rfq_detail", kwargs={"code": quote.rfq.code}
                )
                req.view_label = _("Təklifə bax")
        bits = [code or f"#{req.entity_id}"]
        if payload.get("amount") not in (None, ""):
            bits.append(f"{payload.get('amount')} {payload.get('currency') or 'AZN'}")
        if payload.get("unit_price"):
            bits.append(f"qiymət {payload.get('unit_price')}")
        if payload.get("supplier_id"):
            bits.append(f"podratçı #{payload.get('supplier_id')}")
        req.detail_bits = " · ".join(bits)
    return rows


class ProcurementPendingApprovalsView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    """Supply read-only inbox of pending PR / commitment approvals (no decide)."""

    template_name = "erp/procurement_pending_approvals.html"
    permission_required = "procurement.view"
    permission_denied_message = "Satınalmaya baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        kind = (self.request.GET.get("kind") or "all").strip().lower()
        if kind not in {"all", "pr", "commitment"}:
            kind = "all"
        rows = ProcurementService.list_pending_procurement_approvals(kind=kind)
        _annotate_procurement_approval_links(rows)
        ctx.update(
            {
                "pending": rows,
                "pending_total": len(rows),
                "kind": kind,
                "can_decide": False,
                "page_title": _("Rəhbər təsdiqini gözləyən alışlar"),
            }
        )
        return ctx


class ProcurementReadyToIssueView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    """Issuable Management commitments — same selector as the Supply dashboard card."""

    template_name = "erp/procurement_ready_to_issue.html"
    permission_required = "procurement.view"
    permission_denied_message = "Satınalmaya baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        rows = ProcurementService.list_issuable_commitments()
        _annotate_procurement_approval_links(rows)
        ctx.update(
            {
                "ready": rows,
                "ready_total": len(rows),
                "ready_ids": [r.pk for r in rows],
                "page_title": _("Təsdiqlənib sifarişə hazır olan alışlar"),
                "can_edit_procurement": _can_edit(self.request.user),
            }
        )
        return ctx
