"""Finance portal views — A.4–A.7 accountant workspace."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.mixins import FinancePortalMixin
from apps.accounts.models import Role
from apps.accounting.models import Account, AccountingPeriod, JournalEntry
from apps.accounting.services import (
    AccountingService,
    import_coa_from_xlsx,
    seed_minimal_coa,
    trial_balance,
)
from apps.billing.models import Charge, Invoice, InvoiceStatus, Payment
from apps.billing.policy import in_invoice_window
from apps.billing.services import (
    apply_penalty_charge,
    ar_aging_buckets,
    confirm_invoice,
    generate_invoice_from_charges,
    invoice_balance,
    invoice_vat_summary,
    mark_overdue_invoices,
    record_payment,
)
from apps.core.services import DomainError
from apps.finance.access import (
    can_approve_payment,
    can_close_period,
    can_mutate_finance,
)
from apps.finance.reports import (
    aging_xlsx_response,
    invoices_xlsx_response,
    trial_balance_xlsx_response,
)
from apps.leases.lease_ops import generate_monthly_lease_charges
from apps.parties.models import Party
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

WF_PAYMENT = "finance.payment"


class HomeView(FinancePortalMixin, TemplateView):
    template_name = "finance/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        mark_overdue_invoices()
        open_inv = Invoice.objects.filter(
            status__in=(InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE)
        )
        unbilled = Charge.objects.filter(invoice__isnull=True).count()
        draft_count = Invoice.objects.filter(status=InvoiceStatus.DRAFT).count()
        unposted = JournalEntry.objects.filter(posted=False).count()
        pending_pay = ApprovalRequest.objects.filter(
            workflow_code=WF_PAYMENT, status=ApprovalStatus.PENDING
        ).count()
        ar_total = sum(
            (invoice_balance(i) for i in open_inv.select_related("party")), Decimal("0")
        )
        ctx.update(
            {
                "open_invoice_count": open_inv.count(),
                "unbilled_count": unbilled,
                "draft_count": draft_count,
                "unposted_je": unposted,
                "pending_payments": pending_pay,
                "ar_total": ar_total,
                "in_invoice_window": in_invoice_window(),
                "paid_month": Payment.objects.filter(
                    paid_at__year=timezone.localdate().year,
                    paid_at__month=timezone.localdate().month,
                ).count(),
                "can_mutate": can_mutate_finance(self.request.user),
                "can_approve": can_approve_payment(self.request.user),
            }
        )
        return ctx


class ChargesView(FinancePortalMixin, TemplateView):
    template_name = "finance/charges.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["charges"] = Charge.objects.select_related(
            "party", "lease", "space", "invoice"
        )[:200]
        parties = {}
        for c in Charge.objects.filter(invoice__isnull=True).select_related("party"):
            parties.setdefault(
                c.party_id, {"party": c.party, "ids": [], "total": Decimal("0")}
            )
            parties[c.party_id]["ids"].append(c.pk)
            parties[c.party_id]["total"] += c.amount or Decimal("0")
        ctx["party_groups"] = list(parties.values())
        ctx["can_mutate"] = can_mutate_finance(self.request.user)
        ctx["in_invoice_window"] = in_invoice_window()
        return ctx

    def post(self, request, *args, **kwargs):
        if not can_mutate_finance(request.user):
            messages.error(request, _("İcazə yoxdur."))
            return redirect("finance:charges")
        action = request.POST.get("action")
        try:
            if action == "generate_lease_charges":
                if not in_invoice_window() and request.POST.get("force") != "1":
                    messages.warning(
                        request,
                        _("Invoice pəncərəsi ayın 1–5-i (A.5). Force ilə davam edə bilərsiniz."),
                    )
                stats = generate_monthly_lease_charges()
                messages.success(request, _("İcarə charge: %(stats)s") % {"stats": stats})
            elif action == "invoice_party":
                party = get_object_or_404(Party, pk=request.POST.get("party_id"))
                ids = list(
                    Charge.objects.filter(party=party, invoice__isnull=True).values_list(
                        "pk", flat=True
                    )[:100]
                )
                if not ids:
                    messages.warning(request, _("Fakturasız charge yoxdur."))
                else:
                    inv = generate_invoice_from_charges(party, ids)
                    messages.success(
                        request, _("Draft faktura: %(code)s") % {"code": inv.code}
                    )
                    return redirect("finance:invoice_detail", code=inv.code)
        except (ValueError, DomainError) as exc:
            messages.error(request, str(exc))
        return redirect("finance:charges")


class InvoicesView(FinancePortalMixin, TemplateView):
    template_name = "finance/invoices.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        mark_overdue_invoices()
        status = self.request.GET.get("status", "")
        qs = Invoice.objects.select_related("party", "lease").order_by("-issue_date", "-id")
        if status:
            qs = qs.filter(status=status)
        ctx["invoices"] = qs[:200]
        ctx["status_filter"] = status
        ctx["statuses"] = InvoiceStatus.choices
        ctx["can_mutate"] = can_mutate_finance(self.request.user)
        return ctx


class InvoiceExportView(FinancePortalMixin, View):
    def get(self, request, *args, **kwargs):
        qs = Invoice.objects.select_related("party").order_by("-issue_date")[:2000]
        return invoices_xlsx_response(qs)


class InvoiceDetailView(FinancePortalMixin, TemplateView):
    template_name = "finance/invoice_detail.html"

    def get_invoice(self):
        return get_object_or_404(
            Invoice.objects.select_related("party", "lease").prefetch_related(
                "lines", "payments", "charges"
            ),
            code=self.kwargs["code"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        inv = self.get_invoice()
        pending = ApprovalRequest.objects.filter(
            workflow_code=WF_PAYMENT,
            status=ApprovalStatus.PENDING,
            payload__invoice_id=inv.pk,
        ).first()
        ctx["invoice"] = inv
        ctx["balance"] = invoice_balance(inv)
        ctx["vat_summary"] = invoice_vat_summary(inv)
        ctx["can_mutate"] = can_mutate_finance(self.request.user)
        ctx["can_approve"] = can_approve_payment(self.request.user)
        ctx["pending_payment"] = pending
        return ctx

    def post(self, request, *args, **kwargs):
        inv = self.get_invoice()
        action = request.POST.get("action")
        try:
            if action == "confirm":
                if not can_mutate_finance(request.user):
                    raise DomainError(_("İcazə yoxdur."))
                confirm_invoice(inv, actor=request.user)
                messages.success(request, _("Faktura təsdiqləndi (ISSUED)."))
            elif action == "request_pay":
                if not can_mutate_finance(request.user):
                    raise DomainError(_("İcazə yoxdur."))
                if inv.status not in (InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE):
                    raise DomainError(_("Yalnız təsdiqlənmiş faktura."))
                raw = request.POST.get("amount") or "0"
                amount = Decimal(raw)
                if amount <= 0:
                    raise DomainError(_("Məbləğ müsbət olmalıdır."))
                exists = ApprovalRequest.objects.filter(
                    workflow_code=WF_PAYMENT,
                    status=ApprovalStatus.PENDING,
                    payload__invoice_id=inv.pk,
                ).exists()
                if exists:
                    raise DomainError(_("Gözləyən ödəniş sorğusu artıq var."))
                ApprovalService.request(
                    workflow_code=WF_PAYMENT,
                    requested_by=request.user,
                    entity=inv,
                    payload={
                        "invoice_id": inv.pk,
                        "invoice_code": inv.code,
                        "amount": str(amount),
                        "method": request.POST.get("method") or "bank",
                        "reference": request.POST.get("reference") or "",
                    },
                )
                messages.success(request, _("Ödəniş rəhbərliyə göndərildi."))
            elif action == "approve_pay":
                if not can_approve_payment(request.user):
                    raise DomainError(_("Yalnız rəhbərlik təsdiq edə bilər."))
                req = get_object_or_404(
                    ApprovalRequest,
                    pk=request.POST.get("approval_id"),
                    workflow_code=WF_PAYMENT,
                    status=ApprovalStatus.PENDING,
                )
                ApprovalService.decide(req, approved=True, decided_by=request.user)
                payload = req.payload or {}
                record_payment(
                    invoice=inv,
                    amount=Decimal(payload.get("amount") or 0),
                    method=payload.get("method") or "bank",
                    reference=payload.get("reference") or "",
                )
                messages.success(request, _("Ödəniş təsdiqləndi və qeydə alındı."))
            elif action == "reject_pay":
                if not can_approve_payment(request.user):
                    raise DomainError(_("Yalnız rəhbərlik rədd edə bilər."))
                req = get_object_or_404(
                    ApprovalRequest,
                    pk=request.POST.get("approval_id"),
                    workflow_code=WF_PAYMENT,
                    status=ApprovalStatus.PENDING,
                )
                ApprovalService.decide(
                    req,
                    approved=False,
                    decided_by=request.user,
                    comment=request.POST.get("comment") or "",
                )
                messages.info(request, _("Ödəniş rədd edildi."))
            elif action == "void":
                if not can_mutate_finance(request.user):
                    raise DomainError(_("İcazə yoxdur."))
                if inv.payments.exists():
                    raise DomainError(_("Ödənişi olan faktura ləğv edilə bilməz."))
                inv.status = InvoiceStatus.VOID
                inv.save(update_fields=["status"])
                messages.success(request, _("Faktura ləğv edildi."))
            elif action == "penalty":
                if not can_mutate_finance(request.user):
                    raise DomainError(_("İcazə yoxdur."))
                apply_penalty_charge(
                    inv,
                    amount=request.POST.get("penalty_amount") or 0,
                    description=request.POST.get("penalty_desc") or "",
                )
                messages.success(request, _("Cərimə charge yaradıldı."))
        except (DomainError, InvalidOperation, ValueError) as exc:
            messages.error(request, str(exc))
        return redirect("finance:invoice_detail", code=inv.code)


class PaymentsView(FinancePortalMixin, TemplateView):
    template_name = "finance/payments.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["payments"] = Payment.objects.select_related("invoice", "invoice__party")[:200]
        ctx["pending"] = ApprovalRequest.objects.filter(
            workflow_code=WF_PAYMENT, status=ApprovalStatus.PENDING
        ).select_related("requested_by")[:50]
        ctx["can_approve"] = can_approve_payment(self.request.user)
        return ctx

    def post(self, request, *args, **kwargs):
        if not can_approve_payment(request.user):
            messages.error(request, _("Yalnız rəhbərlik təsdiq edə bilər."))
            return redirect("finance:payments")
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
                    req, approved=False, decided_by=request.user, comment=request.POST.get("comment") or ""
                )
                messages.info(request, _("Ödəniş rədd edildi."))
        except (DomainError, InvalidOperation, ValueError) as exc:
            messages.error(request, str(exc))
        return redirect("finance:payments")


class AgingView(FinancePortalMixin, TemplateView):
    template_name = "finance/aging.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        buckets = ar_aging_buckets()
        ctx["buckets"] = buckets
        ctx["totals"] = {
            k: sum((r["balance"] for r in rows), Decimal("0")) for k, rows in buckets.items()
        }
        return ctx


class AgingExportView(FinancePortalMixin, View):
    def get(self, request, *args, **kwargs):
        return aging_xlsx_response(ar_aging_buckets())


class AccountsView(FinancePortalMixin, TemplateView):
    template_name = "finance/accounts.html"

    def get_context_data(self, **kwargs):
        seed_minimal_coa()
        ctx = super().get_context_data(**kwargs)
        ctx["accounts"] = Account.objects.filter(is_active=True)
        ctx["can_mutate"] = can_mutate_finance(self.request.user)
        return ctx

    def post(self, request, *args, **kwargs):
        if not can_mutate_finance(request.user):
            messages.error(request, _("İcazə yoxdur."))
            return redirect("finance:accounts")
        upload = request.FILES.get("coa_file")
        if not upload:
            messages.error(request, _("Fayl seçin (xlsx)."))
            return redirect("finance:accounts")
        try:
            stats = import_coa_from_xlsx(upload.read())
            messages.success(request, _("CoA import: %(stats)s") % {"stats": stats})
        except Exception as exc:  # noqa: BLE001
            messages.error(request, str(exc))
        return redirect("finance:accounts")


class JournalsView(FinancePortalMixin, TemplateView):
    template_name = "finance/journals.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        ctx["entries"] = JournalEntry.objects.prefetch_related("lines__account")[:100]
        ctx["unposted_today"] = JournalEntry.objects.filter(
            posted=False, entry_date=today
        ).count()
        ctx["can_mutate"] = can_mutate_finance(self.request.user)
        return ctx

    def post(self, request, *args, **kwargs):
        if not can_mutate_finance(request.user):
            messages.error(request, _("İcazə yoxdur."))
            return redirect("finance:journals")
        if request.POST.get("action") == "post_gl":
            entry = get_object_or_404(JournalEntry, pk=request.POST.get("entry_id"))
            try:
                AccountingService.post_to_gl(entry, actor=request.user)
                messages.success(request, _("Baş kitaba yazıldı: %(code)s") % {"code": entry.code})
            except DomainError as exc:
                messages.error(request, str(exc))
        return redirect("finance:journals")


class JournalCreateView(FinancePortalMixin, TemplateView):
    template_name = "finance/journal_form.html"

    def get_context_data(self, **kwargs):
        seed_minimal_coa()
        ctx = super().get_context_data(**kwargs)
        ctx["accounts"] = Account.objects.filter(is_active=True)
        ctx["can_mutate"] = can_mutate_finance(self.request.user)
        return ctx

    def post(self, request, *args, **kwargs):
        if not can_mutate_finance(request.user):
            messages.error(request, _("İcazə yoxdur."))
            return redirect("finance:journals")
        memo = request.POST.get("memo") or ""
        codes = request.POST.getlist("account_code")
        debits = request.POST.getlist("debit")
        credits = request.POST.getlist("credit")
        lines = []
        for i, code in enumerate(codes):
            if not code:
                continue
            try:
                d = Decimal(debits[i] or 0)
                c = Decimal(credits[i] or 0)
            except (InvalidOperation, IndexError):
                continue
            if d == 0 and c == 0:
                continue
            lines.append({"account_code": code, "debit": d, "credit": c})
        try:
            # Manual JE still draft until post_to_gl
            entry = AccountingService.post_journal(
                lines=lines, memo=memo, source="manual", actor=request.user, posted=False
            )
            messages.success(request, _("Jurnal (draft): %(code)s") % {"code": entry.code})
            return redirect("finance:journals")
        except DomainError as exc:
            messages.error(request, str(exc))
            return redirect("finance:journal_create")


class TrialBalanceView(FinancePortalMixin, TemplateView):
    template_name = "finance/trial_balance.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        try:
            year = int(self.request.GET.get("year") or today.year)
            month = int(self.request.GET.get("month") or 0)
        except ValueError:
            year, month = today.year, 0
        rows = trial_balance(year=year, month=month or None)
        ctx["rows"] = rows
        ctx["year"] = year
        ctx["month"] = month
        ctx["total_debit"] = sum((r["debit"] for r in rows), Decimal("0"))
        ctx["total_credit"] = sum((r["credit"] for r in rows), Decimal("0"))
        return ctx


class TrialBalanceExportView(FinancePortalMixin, View):
    def get(self, request, *args, **kwargs):
        today = timezone.localdate()
        try:
            year = int(request.GET.get("year") or today.year)
            month = int(request.GET.get("month") or 0)
        except ValueError:
            year, month = today.year, 0
        return trial_balance_xlsx_response(trial_balance(year=year, month=month or None))


class PeriodsView(FinancePortalMixin, TemplateView):
    template_name = "finance/periods.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        for offset in range(0, 6):
            y, m = today.year, today.month - offset
            while m <= 0:
                m += 12
                y -= 1
            AccountingPeriod.objects.get_or_create(year=y, month=m)
        ctx["periods"] = AccountingPeriod.objects.all()[:24]
        ctx["can_close"] = can_close_period(self.request.user)
        ctx["can_reopen"] = self.request.user.role == Role.MANAGEMENT
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        try:
            year = int(request.POST.get("year"))
            month = int(request.POST.get("month"))
        except (TypeError, ValueError):
            messages.error(request, _("Yanlış dövr."))
            return redirect("finance:periods")
        try:
            if action == "close":
                if not can_close_period(request.user):
                    raise DomainError(_("İcazə yoxdur."))
                AccountingService.close_period(year=year, month=month, actor=request.user)
                messages.success(request, _("Dövr bağlandı."))
            elif action == "reopen":
                if request.user.role != Role.MANAGEMENT:
                    raise DomainError(_("Yalnız rəhbərlik aça bilər."))
                AccountingService.reopen_period(year=year, month=month)
                messages.success(request, _("Dövr yenidən açıldı."))
        except DomainError as exc:
            messages.error(request, str(exc))
        return redirect("finance:periods")
