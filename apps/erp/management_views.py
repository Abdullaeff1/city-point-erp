"""Rəhbərlik funksiyaları ERP daxilində — təsdiqlər, ödəniş, aging, dövrlər."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import models, transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from apps.accounts.mixins import PermissionRequiredMixin, RoleRequiredMixin
from apps.accounts.models import Role
from apps.rbac.services import require_permission
from apps.accounting.models import AccountingPeriod
from apps.accounting.services import AccountingService
from apps.billing.models import Invoice, Payment, SupplierPayment
from apps.billing.services import ar_aging_buckets, record_payment
from apps.core.services import DomainError
from apps.crm.models import OfferVersion
from apps.crm.services import CrmOfferService
from apps.documents.services import WF_DOCUMENT_APPROVE, DocumentService
from apps.finance.access import can_approve_payment
from apps.finance.ap_services import WF_SUPPLIER_PAYMENT
from apps.management.access import can_decide_approvals
from apps.procurement.services import WF_PROCUREMENT_COMMITMENT
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

WF_PAYMENT = "finance.payment"
WF_OFFER = "crm.offer.send"
WF_PROCUREMENT_PR = "procurement.pr"
WF_PROCUREMENT_COMMIT = WF_PROCUREMENT_COMMITMENT
WF_DOCUMENT = WF_DOCUMENT_APPROVE
MGMT_WORKFLOWS = (
    WF_OFFER,
    WF_PAYMENT,
    WF_SUPPLIER_PAYMENT,
    WF_PROCUREMENT_PR,
    WF_PROCUREMENT_COMMIT,
    WF_DOCUMENT,
)


def _document_view_url(req: ApprovalRequest) -> tuple[str | None, str]:
    payload = req.payload or {}
    doc_id = payload.get("document_id")
    version_id = payload.get("version_id")
    if not doc_id:
        return None, ""
    url = reverse("erp:document_download", kwargs={"pk": doc_id})
    if version_id:
        url = f"{url}?version={version_id}"
    return url, _("Versiyanı aç")


class ApprovalsView(PermissionRequiredMixin, RoleRequiredMixin, TemplateView):
    template_name = "erp/approvals.html"
    allowed_roles = (Role.MANAGEMENT,)
    permission_required = "approval.view"
    permission_denied_message = "Təsdiqlərə baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        workflow = (self.request.GET.get("workflow") or "").strip()
        wf_filter = MGMT_WORKFLOWS
        if workflow == "crm.offer.send":
            wf_filter = (WF_OFFER,)
        elif workflow == "document.approve":
            wf_filter = (WF_DOCUMENT,)
        elif workflow == "procurement":
            wf_filter = (WF_PROCUREMENT_PR, WF_PROCUREMENT_COMMIT)
        elif workflow == "finance.payment":
            wf_filter = (WF_PAYMENT,)
        elif workflow == WF_SUPPLIER_PAYMENT:
            wf_filter = (WF_SUPPLIER_PAYMENT,)
        elif workflow and workflow in MGMT_WORKFLOWS:
            wf_filter = (workflow,)
        pending = list(
            ApprovalRequest.objects.filter(
                workflow_code__in=wf_filter, status=ApprovalStatus.PENDING
            )
            .select_related("requested_by", "entity_type")
            .order_by("created_at")[:100]
        )
        ctx["workflow_filter"] = workflow
        for req in pending:
            req.view_url = None
            req.view_label = ""
            req.detail_bits = ""
            req.kind_label = req.workflow_code
            payload = req.payload or {}
            if req.workflow_code == WF_OFFER:
                req.kind_label = _("CRM təklif")
                offer_id = payload.get("offer_id")
                if not offer_id:
                    version = req.entity
                    if version is None:
                        version = OfferVersion.objects.filter(approval_request=req).first()
                    offer_id = getattr(version, "offer_id", None)
                if offer_id:
                    req.view_url = reverse("erp:crm_offer_detail", kwargs={"pk": offer_id})
                    req.view_label = _("Təklifə bax")
                req.detail_bits = f"v{payload.get('version_number') or '—'}"
            elif req.workflow_code == WF_PAYMENT:
                req.kind_label = _("Ödəniş")
                req.detail_bits = (
                    f"{payload.get('invoice_code') or '—'} · "
                    f"{payload.get('amount') or '—'} {payload.get('method') or ''}"
                ).strip()
            elif req.workflow_code in {WF_PROCUREMENT_PR, WF_PROCUREMENT_COMMIT}:
                is_commit = req.workflow_code == WF_PROCUREMENT_COMMIT
                req.kind_label = _("Satınalma öhdəlik") if is_commit else _("Satınalma")
                pr_id = payload.get("pr_id") or req.entity_id
                code = payload.get("code") or ""
                amount_raw = payload.get("amount")
                currency = (payload.get("currency") or "").strip()
                reason = payload.get("escalation_reason") or ""
                limit_amount = payload.get("limit_amount") or ""
                if code:
                    req.view_url = reverse("erp:procurement_pr_detail", kwargs={"code": code})
                else:
                    req.view_url = reverse("erp:procurement")
                req.view_label = _("PR-ə bax")
                if is_commit and payload.get("quote_id"):
                    # Prefer RFQ detail when quotation id is present on the PR's RFQs.
                    from apps.procurement.models import RFQQuote

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
                reason_label = {
                    "amount_unknown": _("məbləğ müəyyən deyil"),
                    "amount_unusable": _("məbləğ müəyyən deyil"),
                    "empty_request": _("sətir yoxdur"),
                    "limit_missing": _("limit yoxdur"),
                    "over_limit": _("limit aşılır"),
                    "over_limit_or_no_limit": _("limit / yoxdur"),
                    "currency_unsupported": _("valyuta dəstəklənmir"),
                }.get(reason, reason)
                if amount_raw not in (None, ""):
                    money = f"{amount_raw} {currency or 'AZN'}"
                    if limit_amount:
                        money = f"{money} (limit {limit_amount} AZN)"
                    if is_commit and payload.get("unit_price"):
                        money = f"{money} · qiymət {payload.get('unit_price')}"
                    if is_commit and payload.get("tax_basis"):
                        money = f"{money} · vergi: {payload.get('tax_basis')}"
                else:
                    money = _("Məbləğ müəyyən edilməyib")
                req.detail_bits = f"{code or pr_id} · {money}"
                if reason_label:
                    req.detail_bits = f"{req.detail_bits} · {reason_label}"
            elif req.workflow_code == WF_DOCUMENT:
                req.kind_label = _("Sənəd")
                title = payload.get("document_title") or f"#{payload.get('document_id')}"
                ver = payload.get("version_label") or "—"
                dept = payload.get("department") or ""
                req.detail_bits = f"{title} · v{ver}"
                if dept:
                    req.detail_bits = f"{req.detail_bits} · {dept}"
                req.view_url, req.view_label = _document_view_url(req)
        history = list(
            ApprovalRequest.objects.filter(workflow_code__in=MGMT_WORKFLOWS)
            .exclude(status=ApprovalStatus.PENDING)
            .select_related("requested_by", "decided_by")
            .order_by("-decided_at", "-updated_at")[:50]
        )
        ctx["pending"] = pending
        ctx["history"] = history
        ctx["can_decide"] = can_decide_approvals(self.request.user)
        return ctx

    def post(self, request, *args, **kwargs):
        require_permission(
            request.user,
            "approval.decide",
            message=_("Təsdiq qərarı vermək icazəniz yoxdur."),
        )
        if not can_decide_approvals(request.user):
            messages.error(request, _("İcazə yoxdur."))
            return redirect("erp:approvals")
        action = request.POST.get("action")
        req = get_object_or_404(
            ApprovalRequest,
            pk=request.POST.get("approval_id"),
            status=ApprovalStatus.PENDING,
            workflow_code__in=MGMT_WORKFLOWS,
        )
        approved = action == "approve"
        comment = request.POST.get("comment") or ""
        try:
            with transaction.atomic():
                if req.workflow_code == WF_OFFER:
                    version = req.entity
                    if version is None:
                        version = OfferVersion.objects.filter(approval_request=req).first()
                    if version is None:
                        raise DomainError(_("Təklif versiyası tapılmadı."))
                    CrmOfferService.decide_approval(
                        version, actor=request.user, approved=approved, comment=comment
                    )
                    messages.success(
                        request,
                        _("Təklif təsdiqləndi.") if approved else _("Təklif rədd edildi."),
                    )
                elif req.workflow_code == WF_PAYMENT:
                    if not can_approve_payment(request.user):
                        raise DomainError(_("Ödəniş təsdiqi icazəsi yoxdur."))
                    ApprovalService.decide(
                        req, approved=approved, decided_by=request.user, comment=comment
                    )
                    if approved:
                        req.refresh_from_db()
                        payload = req.payload or {}
                        inv = get_object_or_404(Invoice, pk=payload.get("invoice_id"))
                        record_payment(
                            invoice=inv,
                            amount=Decimal(payload.get("amount") or 0),
                            method=payload.get("method") or "bank",
                            reference=payload.get("reference") or "",
                            approval_request=req,
                        )
                        messages.success(request, _("Ödəniş təsdiqləndi."))
                    else:
                        messages.info(request, _("Ödəniş rədd edildi."))
                elif req.workflow_code == WF_PROCUREMENT_PR:
                    from apps.procurement.services import ProcurementService

                    ProcurementService.decide_management_pr(
                        req, approved=approved, actor=request.user, comment=comment
                    )
                    messages.success(
                        request,
                        _("Satınalma təsdiqləndi.") if approved else _("Satınalma rədd edildi."),
                    )
                elif req.workflow_code == WF_PROCUREMENT_COMMIT:
                    from apps.procurement.services import ProcurementService

                    ProcurementService.decide_management_commitment(
                        req, approved=approved, actor=request.user, comment=comment
                    )
                    messages.success(
                        request,
                        _("Öhdəlik təsdiqləndi.") if approved else _("Öhdəlik rədd edildi."),
                    )
                elif req.workflow_code == WF_DOCUMENT:
                    DocumentService.decide_approval(
                        req, actor=request.user, approved=approved, comment=comment
                    )
                    messages.success(
                        request,
                        _("Sənəd təsdiqləndi.") if approved else _("Sənəd rədd edildi."),
                    )
        except DomainError as exc:
            messages.error(request, str(exc))
        except (InvalidOperation, ValueError, TypeError) as exc:
            messages.error(request, str(exc))
        return redirect("erp:approvals")


class PaymentApprovalsView(RoleRequiredMixin, TemplateView):
    template_name = "erp/payment_approvals.html"
    allowed_roles = (Role.MANAGEMENT,)

    def get_context_data(self, **kwargs):
        from decimal import Decimal

        from apps.billing.evidence_models import EvidenceStatus, InvoicePaymentEvidence
        from apps.workflows.models import ApprovalRequest as AR
        from apps.workflows.models import ApprovalStatus as AS

        ctx = super().get_context_data(**kwargs)
        queue = (self.request.GET.get("queue") or "").strip().lower()
        if queue not in {"ar", "ap", ""}:
            queue = ""
        show_ar = queue in {"", "ar"}
        show_ap = queue in {"", "ap"}
        ctx["queue"] = queue or "all"
        ctx["show_ar"] = show_ar
        ctx["show_ap"] = show_ap
        pending_ar = list(
            ApprovalRequest.objects.filter(
                workflow_code=WF_PAYMENT, status=ApprovalStatus.PENDING
            ).select_related("requested_by")[:50]
        ) if show_ar else []
        pending_ap = list(
            ApprovalRequest.objects.filter(
                workflow_code=WF_SUPPLIER_PAYMENT, status=ApprovalStatus.PENDING
            ).select_related("requested_by")[:50]
        ) if show_ap else []
        # Enrich AP rows with Decision 04 decision context from payload.
        for req in pending_ap:
            p = req.payload or {}
            req.decision_ctx = {
                "payee": p.get("payee_name") or "—",
                "purpose": p.get("purpose") or "—",
                "currency": p.get("currency") or "AZN",
                "amount_now": p.get("amount_requested_now") or p.get("amount"),
                "liability": p.get("liability_gross") or "—",
                "prior_settled": p.get("prior_settled") or "0",
                "pending_reservations": p.get("pending_reservations") or "0",
                "remainder": p.get("expected_remainder") or "—",
                "po_code": p.get("po_code") or "—",
                "pr_code": p.get("pr_code") or "—",
                "net": p.get("net_amount") or "—",
                "vat": p.get("vat_amount") if p.get("tax_known") else "naməlum",
                "match_status": p.get("match_status") or "—",
                "invoice_url": (
                    f"/finance/payables/{p.get('supplier_invoice_code')}/"
                    if p.get("supplier_invoice_code")
                    else ""
                ),
            }
        ctx["pending"] = pending_ar
        ctx["pending_supplier"] = pending_ap
        ctx["payments"] = (
            Payment.objects.select_related("invoice", "invoice__party")[:100] if show_ar else []
        )
        ctx["supplier_payments"] = (
            SupplierPayment.objects.select_related(
                "supplier_invoice", "supplier_invoice__supplier_party"
            )[:100]
            if show_ap
            else []
        )
        ctx["can_approve"] = can_approve_payment(self.request.user)
        # Management RO money strip — directions and statuses labelled (Decision 04).
        def _sum_payload(qs):
            total = Decimal("0.00")
            for r in qs:
                try:
                    total += Decimal(str((r.payload or {}).get("amount") or 0))
                except Exception:  # noqa: BLE001
                    continue
            return total.quantize(Decimal("0.01"))

        ar_pending_amt = _sum_payload(
            AR.objects.filter(workflow_code=WF_PAYMENT, status=AS.PENDING)
        )
        ap_pending_amt = _sum_payload(
            AR.objects.filter(workflow_code=WF_SUPPLIER_PAYMENT, status=AS.PENDING)
        )
        ap_approved_unsettled = Decimal("0.00")
        for r in AR.objects.filter(
            workflow_code=WF_SUPPLIER_PAYMENT, status=AS.APPROVED
        ).iterator():
            p = r.payload or {}
            if p.get("supplier_payment_id"):
                continue
            try:
                ap_approved_unsettled += Decimal(str(p.get("amount") or 0))
            except Exception:  # noqa: BLE001
                continue
        ap_approved_unsettled = ap_approved_unsettled.quantize(Decimal("0.01"))
        ar_settled = Payment.objects.aggregate(s=models.Sum("amount"))["s"] or Decimal("0")
        ap_settled = SupplierPayment.objects.aggregate(s=models.Sum("amount"))["s"] or Decimal(
            "0"
        )
        evidence_pending = InvoicePaymentEvidence.objects.filter(
            status=EvidenceStatus.PENDING_REVIEW
        ).count()
        ctx["money_totals"] = {
            "ar_pending_legacy": ar_pending_amt,
            "ar_settled": ar_settled.quantize(Decimal("0.01")),
            "ap_pending": ap_pending_amt,
            "ap_approved_unsettled": ap_approved_unsettled,
            "ap_settled": ap_settled.quantize(Decimal("0.01")),
            "evidence_pending_count": evidence_pending,
            "currency": "AZN",
        }
        ctx["ar_primary_path_note"] = (
            "Daxil olan (AR) ödəniş sübutu Mühasib yoxlaması ilə qeydə alınır; "
            "aşağıdakı AR approval növbəsi yalnız köhnə sorğular üçündür."
        )
        return ctx

    def post(self, request, *args, **kwargs):
        if not can_approve_payment(request.user):
            messages.error(request, _("Yalnız rəhbərlik təsdiq edə bilər."))
            return redirect("erp:payment_approvals")
        queue = (request.GET.get("queue") or request.POST.get("queue") or "").strip().lower()
        redirect_url = reverse("erp:payment_approvals")
        if queue in {"ar", "ap"}:
            redirect_url = f"{redirect_url}?queue={queue}"
        action = request.POST.get("action")
        try:
            if action in ("approve_pay", "reject_pay"):
                req = get_object_or_404(
                    ApprovalRequest,
                    pk=request.POST.get("approval_id"),
                    workflow_code=WF_PAYMENT,
                    status=ApprovalStatus.PENDING,
                )
                if action == "approve_pay":
                    ApprovalService.decide(req, approved=True, decided_by=request.user)
                    req.refresh_from_db()
                    payload = req.payload or {}
                    inv = get_object_or_404(Invoice, pk=payload.get("invoice_id"))
                    record_payment(
                        invoice=inv,
                        amount=Decimal(payload.get("amount") or 0),
                        method=payload.get("method") or "bank",
                        reference=payload.get("reference") or "",
                        approval_request=req,
                    )
                    messages.success(request, _("Kiracı ödənişi təsdiqləndi."))
                else:
                    ApprovalService.decide(
                        req,
                        approved=False,
                        decided_by=request.user,
                        comment=request.POST.get("comment") or "",
                    )
                    messages.info(request, _("Kiracı ödənişi rədd edildi."))
            elif action in ("approve_supplier_pay", "reject_supplier_pay"):
                req = get_object_or_404(
                    ApprovalRequest,
                    pk=request.POST.get("approval_id"),
                    workflow_code=WF_SUPPLIER_PAYMENT,
                    status=ApprovalStatus.PENDING,
                )
                if action == "approve_supplier_pay":
                    # Authorization only — SupplierPayment / ops payable drop on separate settle.
                    ApprovalService.decide(req, approved=True, decided_by=request.user)
                    messages.success(
                        request,
                        _(
                            "Podratçı ödənişi təsdiqləndi. Settlement sübutu "
                            "mühasib tərəfindən AP faktura səhifəsində qeydə alınır."
                        ),
                    )
                else:
                    ApprovalService.decide(
                        req,
                        approved=False,
                        decided_by=request.user,
                        comment=request.POST.get("comment") or "",
                    )
                    messages.info(request, _("Podratçı ödənişi rədd edildi."))
        except (DomainError, InvalidOperation, ValueError) as exc:
            messages.error(request, str(exc))
        return redirect(redirect_url)


class ArAgingView(RoleRequiredMixin, TemplateView):
    template_name = "erp/ar_aging.html"
    allowed_roles = (Role.MANAGEMENT,)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        buckets = ar_aging_buckets()
        ctx["buckets"] = buckets
        ctx["totals"] = {
            k: sum((r["balance"] for r in rows), Decimal("0")) for k, rows in buckets.items()
        }
        return ctx


class AccountingPeriodsView(RoleRequiredMixin, TemplateView):
    template_name = "erp/accounting_periods.html"
    allowed_roles = (Role.MANAGEMENT,)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["periods"] = AccountingPeriod.objects.all()[:24]
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        try:
            year = int(request.POST.get("year") or 0)
            month = int(request.POST.get("month") or 0)
            if action == "reopen":
                AccountingService.reopen_period(year=year, month=month)
                messages.success(request, _("Dövr yenidən açıldı."))
            else:
                messages.error(request, _("Naməlum əməliyyat."))
        except (DomainError, ValueError, TypeError) as exc:
            messages.error(request, str(exc))
        return redirect("erp:accounting_periods")
