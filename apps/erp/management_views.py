"""Rəhbərlik funksiyaları ERP daxilində — təsdiqlər, ödəniş, aging, dövrlər."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from apps.accounts.mixins import PermissionRequiredMixin, RoleRequiredMixin
from apps.accounts.models import Role
from apps.rbac.services import require_permission
from apps.accounting.models import AccountingPeriod
from apps.accounting.services import AccountingService
from apps.billing.models import Invoice, Payment
from apps.billing.services import ar_aging_buckets, record_payment
from apps.core.services import DomainError
from apps.crm.models import OfferVersion
from apps.crm.services import CrmOfferService
from apps.documents.services import WF_DOCUMENT_APPROVE, DocumentService
from apps.finance.access import can_approve_payment
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
        pending = list(
            ApprovalRequest.objects.filter(
                workflow_code__in=MGMT_WORKFLOWS, status=ApprovalStatus.PENDING
            )
            .select_related("requested_by", "entity_type")
            .order_by("created_at")[:100]
        )
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
        ctx = super().get_context_data(**kwargs)
        ctx["pending"] = ApprovalRequest.objects.filter(
            workflow_code=WF_PAYMENT, status=ApprovalStatus.PENDING
        ).select_related("requested_by")[:50]
        ctx["payments"] = Payment.objects.select_related("invoice", "invoice__party")[:100]
        ctx["can_approve"] = can_approve_payment(self.request.user)
        return ctx

    def post(self, request, *args, **kwargs):
        if not can_approve_payment(request.user):
            messages.error(request, _("Yalnız rəhbərlik təsdiq edə bilər."))
            return redirect("erp:payment_approvals")
        action = request.POST.get("action")
        req = get_object_or_404(
            ApprovalRequest,
            pk=request.POST.get("approval_id"),
            workflow_code=WF_PAYMENT,
            status=ApprovalStatus.PENDING,
        )
        try:
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
                messages.success(request, _("Ödəniş təsdiqləndi."))
            elif action == "reject_pay":
                ApprovalService.decide(
                    req,
                    approved=False,
                    decided_by=request.user,
                    comment=request.POST.get("comment") or "",
                )
                messages.info(request, _("Ödəniş rədd edildi."))
        except (DomainError, InvalidOperation, ValueError) as exc:
            messages.error(request, str(exc))
        return redirect("erp:payment_approvals")


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
