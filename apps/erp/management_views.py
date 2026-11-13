"""Rəhbərlik funksiyaları ERP daxilində — təsdiqlər, ödəniş, aging, dövrlər."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from apps.accounts.mixins import RoleRequiredMixin
from apps.accounts.models import Role
from apps.accounting.models import AccountingPeriod
from apps.accounting.services import AccountingService
from apps.billing.models import Invoice, Payment
from apps.billing.services import ar_aging_buckets, record_payment
from apps.core.services import DomainError
from apps.crm.models import OfferVersion
from apps.crm.services import CrmOfferService
from apps.finance.access import can_approve_payment
from apps.management.access import can_decide_approvals
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

WF_PAYMENT = "finance.payment"
WF_OFFER = "crm.offer.send"
MGMT_WORKFLOWS = (WF_OFFER, WF_PAYMENT)


class ApprovalsView(RoleRequiredMixin, TemplateView):
    template_name = "erp/approvals.html"
    allowed_roles = (Role.MANAGEMENT,)

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
            if req.workflow_code == WF_OFFER:
                offer_id = (req.payload or {}).get("offer_id")
                if not offer_id:
                    version = req.entity
                    if version is None:
                        version = OfferVersion.objects.filter(approval_request=req).first()
                    offer_id = getattr(version, "offer_id", None)
                if offer_id:
                    req.view_url = reverse("erp:crm_offer_detail", kwargs={"pk": offer_id})
                    req.view_label = _("Təklifə bax")
            elif req.workflow_code == WF_PAYMENT:
                # Management finance portalına girmir — faktura kodu siyahıda görünür
                pass
        ctx["pending"] = pending
        ctx["can_decide"] = can_decide_approvals(self.request.user)
        return ctx

    def post(self, request, *args, **kwargs):
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
                    payload = req.payload or {}
                    inv = get_object_or_404(Invoice, pk=payload.get("invoice_id"))
                    record_payment(
                        invoice=inv,
                        amount=Decimal(payload.get("amount") or 0),
                        method=payload.get("method") or "bank",
                        reference=payload.get("reference") or "",
                    )
                    messages.success(request, _("Ödəniş təsdiqləndi."))
                else:
                    messages.info(request, _("Ödəniş rədd edildi."))
        except (DomainError, InvalidOperation, ValueError, TypeError) as exc:
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
                payload = req.payload or {}
                inv = get_object_or_404(Invoice, pk=payload.get("invoice_id"))
                record_payment(
                    invoice=inv,
                    amount=Decimal(payload.get("amount") or 0),
                    method=payload.get("method") or "bank",
                    reference=payload.get("reference") or "",
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
