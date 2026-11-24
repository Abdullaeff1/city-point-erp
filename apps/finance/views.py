"""Finance portal views — A.4–A.7 accountant workspace."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.mixins import FinancePortalMixin
from apps.accounting.models import Account, AccountingPeriod, JournalEntry
from apps.accounting.services import (
    AccountingService,
    ensure_period,
    import_coa_from_xlsx,
    seed_minimal_coa,
    trial_balance,
)
from apps.billing.models import (
    Charge,
    ChargeSource,
    Invoice,
    InvoiceStatus,
    Payment,
    SupplierInvoice,
    SupplierInvoiceStatus,
    SupplierPayment,
)
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
    void_invoice,
)
from apps.finance.ap_services import (
    WF_SUPPLIER_PAYMENT,
    SupplierInvoiceService,
    line_match_snapshot,
    authorizable_payable_amount,
    open_payment_authorization_amount,
    payable_balance,
    payable_recon_snapshot,
    posted_ap_balance,
    supplier_invoice_gross,
    supplier_payment_queue_invoice_ids,
)
from apps.finance.dashboard import build_dashboard
from apps.parties.models import Party, PartyStatus
from apps.procurement.models import POLine
from apps.core.services import DomainError
from apps.erp.views import (
    BuildingEquipmentListView as ErpBuildingEquipmentListView,
)
from apps.erp.views import (
    BuildingInventoryListView as ErpBuildingInventoryListView,
)
from apps.finance.access import (
    can_approve_payment,
    can_close_period,
    can_mutate_finance,
    can_reopen_period,
)
from apps.finance.reports import (
    aging_xlsx_response,
    invoices_xlsx_response,
    trial_balance_xlsx_response,
)
from apps.leases.lease_ops import generate_monthly_lease_charges
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

WF_PAYMENT = "finance.payment"


class HomeView(FinancePortalMixin, TemplateView):
    template_name = "finance/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        dash = build_dashboard()
        ctx.update(dash)
        ctx.update(
            {
                "in_invoice_window": in_invoice_window(),
                "unbilled_count": Charge.objects.filter(invoice__isnull=True).count(),
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
                # Phase 4.3 / 11: depozit kirayə/xidmət ilə eyni fakturada ola bilməz.
                non_deposit = list(
                    Charge.objects.filter(party=party, invoice__isnull=True)
                    .exclude(source=ChargeSource.DEPOSIT)
                    .order_by("pk")
                    .values_list("pk", flat=True)[:100]
                )
                deposit_only = list(
                    Charge.objects.filter(
                        party=party,
                        invoice__isnull=True,
                        source=ChargeSource.DEPOSIT,
                    )
                    .order_by("pk")
                    .values_list("pk", flat=True)[:100]
                )
                ids = non_deposit or deposit_only
                if not ids:
                    messages.warning(request, _("Fakturasız charge yoxdur."))
                else:
                    inv = generate_invoice_from_charges(party, ids)
                    if non_deposit and deposit_only:
                        messages.info(
                            request,
                            _("Depozit ayrıca qaldı — növbəti fakturada kəsilə bilər."),
                        )
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
                payload = req.payload or {}
                if int(payload.get("invoice_id") or 0) != inv.pk:
                    raise DomainError(_("Approval bu fakturaya aid deyil."))
                ApprovalService.decide(req, approved=True, decided_by=request.user)
                req.refresh_from_db()
                record_payment(
                    invoice=inv,
                    amount=Decimal(payload.get("amount") or 0),
                    method=payload.get("method") or "bank",
                    reference=payload.get("reference") or "",
                    approval_request=req,
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
                void_invoice(inv, actor=request.user)
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
    """Confirmed payments list, or pending approval inspect (?pending=1).

    Accountant may inspect pending requests; approve/reject remains Management-only
    (A.7) — typically via ERP. POST approve on this portal still gated by can_approve.
    """

    template_name = "finance/payments.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        pending_only = self.request.GET.get("pending") == "1"
        ctx["pending_only"] = pending_only
        ctx["pending"] = ApprovalRequest.objects.filter(
            workflow_code=WF_PAYMENT, status=ApprovalStatus.PENDING
        ).select_related("requested_by")[:50]
        ctx["payments"] = (
            Payment.objects.none()
            if pending_only
            else Payment.objects.select_related("invoice", "invoice__party")[:200]
        )
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
        qs = JournalEntry.objects.prefetch_related("lines__account").order_by(
            "-entry_date", "-id"
        )
        posted_filter = self.request.GET.get("posted", "")
        source_filter = (self.request.GET.get("source") or "").strip()
        if posted_filter == "0":
            qs = qs.filter(posted=False)
        elif posted_filter == "1":
            qs = qs.filter(posted=True)
        if source_filter:
            qs = qs.filter(source=source_filter)
        ctx["entries"] = qs[:100]
        ctx["posted_filter"] = posted_filter
        ctx["source_filter"] = source_filter
        ctx["unposted_count"] = JournalEntry.objects.filter(posted=False).count()
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
            return redirect("finance:journal_detail", code=entry.code)
        return redirect("finance:journals")


class JournalDetailView(FinancePortalMixin, TemplateView):
    """Inspect JE lines, period, and durable billing source link."""

    template_name = "finance/journal_detail.html"

    def get_entry(self):
        return get_object_or_404(
            JournalEntry.objects.prefetch_related("lines__account"),
            code=self.kwargs["code"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        entry = self.get_entry()
        period = ensure_period(entry.entry_date.year, entry.entry_date.month)
        source_invoice = None
        source_payment = None
        source_supplier_invoice = None
        ref = entry.source_ref or ""
        if entry.source == "billing.invoice" and ref.startswith("invoice:"):
            try:
                source_invoice = Invoice.objects.select_related("party").get(
                    pk=int(ref.split(":", 1)[1])
                )
            except (Invoice.DoesNotExist, ValueError, TypeError):
                source_invoice = None
        elif entry.source == "billing.payment" and ref.startswith("payment:"):
            try:
                source_payment = Payment.objects.select_related(
                    "invoice", "invoice__party", "party"
                ).get(pk=int(ref.split(":", 1)[1]))
            except (Payment.DoesNotExist, ValueError, TypeError):
                source_payment = None
        elif entry.source == "billing.supplier_invoice" and ref.startswith(
            "supplier_invoice:"
        ):
            try:
                source_supplier_invoice = SupplierInvoice.objects.select_related(
                    "supplier_party"
                ).get(pk=int(ref.split(":", 1)[1]))
            except (SupplierInvoice.DoesNotExist, ValueError, TypeError):
                source_supplier_invoice = None
        elif entry.source == "billing.supplier_payment" and ref.startswith(
            "supplier_payment:"
        ):
            try:
                sp = SupplierPayment.objects.select_related(
                    "supplier_invoice", "supplier_invoice__supplier_party"
                ).get(pk=int(ref.split(":", 1)[1]))
                source_supplier_invoice = sp.supplier_invoice
            except (SupplierPayment.DoesNotExist, ValueError, TypeError):
                source_supplier_invoice = None
        total_d = sum((ln.debit or Decimal("0") for ln in entry.lines.all()), Decimal("0"))
        total_c = sum((ln.credit or Decimal("0") for ln in entry.lines.all()), Decimal("0"))
        ctx.update(
            {
                "entry": entry,
                "period": period,
                "source_invoice": source_invoice,
                "source_payment": source_payment,
                "source_supplier_invoice": source_supplier_invoice,
                "total_debit": total_d,
                "total_credit": total_c,
                "can_mutate": can_mutate_finance(self.request.user),
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        entry = self.get_entry()
        if not can_mutate_finance(request.user):
            messages.error(request, _("İcazə yoxdur."))
            return redirect("finance:journal_detail", code=entry.code)
        if request.POST.get("action") == "post_gl":
            try:
                AccountingService.post_to_gl(entry, actor=request.user)
                messages.success(request, _("Baş kitaba yazıldı: %(code)s") % {"code": entry.code})
            except DomainError as exc:
                messages.error(request, str(exc))
        return redirect("finance:journal_detail", code=entry.code)


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
        as_of = None
        try:
            year = int(self.request.GET.get("year") or today.year)
            month = int(self.request.GET.get("month") or 0)
            raw_as_of = (self.request.GET.get("as_of") or "").strip()
            if raw_as_of:
                as_of = date.fromisoformat(raw_as_of)
        except ValueError:
            year, month, as_of = today.year, 0, None
        rows = trial_balance(year=year, month=month or None, as_of=as_of)
        ctx["rows"] = rows
        ctx["year"] = year
        ctx["month"] = month
        ctx["as_of"] = as_of.isoformat() if as_of else ""
        ctx["total_debit"] = sum((r["debit"] for r in rows), Decimal("0"))
        ctx["total_credit"] = sum((r["credit"] for r in rows), Decimal("0"))
        ctx["total_opening"] = sum((r.get("opening_balance") or 0 for r in rows), Decimal("0"))
        ctx["total_closing"] = sum((r.get("closing_balance") or r["balance"] for r in rows), Decimal("0"))
        return ctx


class TrialBalanceExportView(FinancePortalMixin, View):
    def get(self, request, *args, **kwargs):
        today = timezone.localdate()
        as_of = None
        try:
            year = int(request.GET.get("year") or today.year)
            month = int(request.GET.get("month") or 0)
            raw_as_of = (request.GET.get("as_of") or "").strip()
            if raw_as_of:
                as_of = date.fromisoformat(raw_as_of)
        except ValueError:
            year, month, as_of = today.year, 0, None
        return trial_balance_xlsx_response(
            trial_balance(year=year, month=month or None, as_of=as_of)
        )


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
        ctx["can_reopen"] = can_reopen_period(self.request.user)
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
                if not can_reopen_period(request.user):
                    raise DomainError(_("İcazə yoxdur."))
                AccountingService.reopen_period(year=year, month=month, actor=request.user)
                messages.success(request, _("Dövr yenidən açıldı."))
        except DomainError as exc:
            messages.error(request, str(exc))
        return redirect("finance:periods")


class BuildingEquipmentListView(FinancePortalMixin, ErpBuildingEquipmentListView):
    """Avadanlıq — maliyyə shell (ERP chrome dəyişməsin)."""

    template_name = "finance/building_assets.html"
    list_url_name = "finance:building_equipment"


class BuildingInventoryListView(FinancePortalMixin, ErpBuildingInventoryListView):
    """İnventar — maliyyə shell."""

    template_name = "finance/building_assets.html"
    list_url_name = "finance:building_inventory"


class PayablesView(FinancePortalMixin, TemplateView):
    """Supplier invoices + AP payment queues (pending / settle / unposted / posted)."""

    template_name = "finance/payables.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        status = self.request.GET.get("status", "")
        queue = (self.request.GET.get("queue") or "").strip()
        qs = SupplierInvoice.objects.select_related("supplier_party", "journal_entry").order_by(
            "-invoice_date", "-id"
        )
        if status:
            qs = qs.filter(status=status)

        payment_rows = None
        if queue in ("pending_approval", "awaiting_settle"):
            ids = supplier_payment_queue_invoice_ids(queue=queue)
            qs = qs.filter(pk__in=ids) if ids else qs.none()
        elif queue == "unposted_settle":
            payment_rows = (
                SupplierPayment.objects.filter(journal_entry__posted=False)
                .select_related(
                    "supplier_invoice",
                    "supplier_invoice__supplier_party",
                    "journal_entry",
                )
                .order_by("-paid_at", "-id")[:200]
            )
            qs = SupplierInvoice.objects.none()
        elif queue == "posted_settle":
            payment_rows = (
                SupplierPayment.objects.filter(journal_entry__posted=True)
                .select_related(
                    "supplier_invoice",
                    "supplier_invoice__supplier_party",
                    "journal_entry",
                )
                .order_by("-paid_at", "-id")[:200]
            )
            qs = SupplierInvoice.objects.none()

        pending_n = ApprovalRequest.objects.filter(
            workflow_code=WF_SUPPLIER_PAYMENT, status=ApprovalStatus.PENDING
        ).count()
        awaiting_n = len(supplier_payment_queue_invoice_ids(queue="awaiting_settle"))
        unposted_n = SupplierPayment.objects.filter(journal_entry__posted=False).count()
        posted_n = SupplierPayment.objects.filter(journal_entry__posted=True).count()

        ctx["invoices"] = qs[:200]
        ctx["payment_rows"] = payment_rows
        ctx["status_filter"] = status
        ctx["queue_filter"] = queue
        ctx["statuses"] = SupplierInvoiceStatus.choices
        ctx["can_mutate"] = can_mutate_finance(self.request.user)
        ctx["queue_counts"] = {
            "pending_approval": pending_n,
            "awaiting_settle": awaiting_n,
            "unposted_settle": unposted_n,
            "posted_settle": posted_n,
        }
        return ctx


class PayableCreateView(FinancePortalMixin, TemplateView):
    template_name = "finance/payable_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["suppliers"] = Party.objects.filter(status=PartyStatus.ACTIVE).order_by(
            "legal_name"
        )[:500]
        ctx["po_lines"] = (
            POLine.objects.select_related("po", "po__supplier_party")
            .filter(received_qty__gt=0)
            .order_by("-po_id", "id")[:300]
        )
        ctx["can_mutate"] = can_mutate_finance(self.request.user)
        return ctx

    def post(self, request, *args, **kwargs):
        if not can_mutate_finance(request.user):
            messages.error(request, _("İcazə yoxdur."))
            return redirect("finance:payables")
        try:
            party = get_object_or_404(Party, pk=request.POST.get("supplier_party"))
            selected = {str(x) for x in request.POST.getlist("selected_po_line")}
            all_ids = request.POST.getlist("row_po_line_id")
            qtys = request.POST.getlist("qty_invoiced")
            prices = request.POST.getlist("unit_price")
            lines = []
            for i, plid in enumerate(all_ids):
                if not plid or str(plid) not in selected:
                    continue
                po_line = POLine.objects.select_related("po").get(pk=plid)
                qty = Decimal(qtys[i] or 0)
                price = Decimal(prices[i] or po_line.unit_price or 0)
                if qty <= 0:
                    continue
                lines.append(
                    {
                        "po_line": po_line,
                        "qty_invoiced": qty,
                        "unit_price": price,
                        "description": po_line.description,
                    }
                )
            raw_date = (request.POST.get("invoice_date") or "").strip()
            inv_date = timezone.localdate()
            if raw_date:
                inv_date = date.fromisoformat(raw_date)
            inv = SupplierInvoiceService.create_draft(
                supplier_party=party,
                supplier_invoice_no=request.POST.get("supplier_invoice_no") or "",
                invoice_date=inv_date,
                currency=request.POST.get("currency") or "AZN",
                notes=request.POST.get("notes") or "",
                lines=lines,
                actor=request.user,
            )
            messages.success(request, _("Podratçı fakturası yaradıldı: %(code)s") % {"code": inv.code})
            return redirect("finance:payable_detail", code=inv.code)
        except (DomainError, InvalidOperation, ValueError, POLine.DoesNotExist) as exc:
            messages.error(request, str(exc))
            return redirect("finance:payable_create")


class PayableDetailView(FinancePortalMixin, TemplateView):
    template_name = "finance/payable_detail.html"

    def get_invoice(self):
        return get_object_or_404(
            SupplierInvoice.objects.select_related(
                "supplier_party", "journal_entry"
            ).prefetch_related("lines__po_line__po"),
            code=self.kwargs["code"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        inv = self.get_invoice()
        line_rows = []
        for ln in inv.lines.all():
            snap = line_match_snapshot(ln)
            line_rows.append({"line": ln, **snap})
        block = None
        if inv.status == SupplierInvoiceStatus.MATCHED:
            block = SupplierInvoiceService.recognition_block_reason(inv)
        pending_pay = ApprovalRequest.objects.filter(
            workflow_code=WF_SUPPLIER_PAYMENT,
            status=ApprovalStatus.PENDING,
            payload__supplier_invoice_id=inv.pk,
        ).first()
        approved_awaiting = [
            req
            for req in ApprovalRequest.objects.filter(
                workflow_code=WF_SUPPLIER_PAYMENT,
                status=ApprovalStatus.APPROVED,
                payload__supplier_invoice_id=inv.pk,
            ).order_by("pk")
            if not (req.payload or {}).get("supplier_payment_id")
        ]
        ctx.update(
            {
                "invoice": inv,
                "line_rows": line_rows,
                "can_mutate": can_mutate_finance(self.request.user),
                "recognition_block": block,
                "gross": supplier_invoice_gross(inv),
                "payable_balance": payable_balance(inv),
                "posted_ap_balance": posted_ap_balance(inv),
                "recon": payable_recon_snapshot(inv),
                "authorizable_amount": authorizable_payable_amount(inv),
                "open_auth_amount": open_payment_authorization_amount(inv),
                "supplier_payments": inv.payments.select_related("journal_entry").all(),
                "pending_supplier_payment": pending_pay,
                "approved_awaiting_settle": approved_awaiting,
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        inv = self.get_invoice()
        if not can_mutate_finance(request.user):
            messages.error(request, _("İcazə yoxdur."))
            return redirect("finance:payable_detail", code=inv.code)
        action = request.POST.get("action")
        try:
            if action == "validate":
                out = SupplierInvoiceService.validate_and_match_or_hold(inv, actor=request.user)
                if out.status == SupplierInvoiceStatus.HOLD:
                    messages.warning(request, out.hold_reason or _("HOLD."))
                else:
                    messages.success(request, _("MATCHED — miqdar rezerv olundu."))
            elif action == "revalidate":
                out = SupplierInvoiceService.revalidate_hold(inv, actor=request.user)
                if out.status == SupplierInvoiceStatus.HOLD:
                    messages.warning(request, out.hold_reason or _("Hələ HOLD."))
                else:
                    messages.success(request, _("Yenidən yoxlama: MATCHED."))
            elif action == "recognize":
                out = SupplierInvoiceService.recognize_payable(inv, actor=request.user)
                messages.success(
                    request,
                    _("AP tanındı (unposted JE): %(code)s")
                    % {"code": out.journal_entry.code if out.journal_entry_id else "—"},
                )
            elif action == "request_pay":
                SupplierInvoiceService.request_supplier_payment(
                    inv,
                    amount=request.POST.get("amount") or 0,
                    actor=request.user,
                    method=request.POST.get("method") or "bank",
                    reference=request.POST.get("reference") or "",
                )
                messages.success(request, _("Podratçı ödəniş sorğusu rəhbərliyə göndərildi."))
            elif action == "settle_pay":
                req = get_object_or_404(
                    ApprovalRequest,
                    pk=request.POST.get("approval_id"),
                    workflow_code=WF_SUPPLIER_PAYMENT,
                    status=ApprovalStatus.APPROVED,
                )
                raw_date = (request.POST.get("paid_at") or "").strip()
                paid_at = date.fromisoformat(raw_date) if raw_date else timezone.localdate()
                pay = SupplierInvoiceService.record_supplier_payment(
                    invoice=inv,
                    amount=request.POST.get("amount") or (req.payload or {}).get("amount") or 0,
                    approval_request=req,
                    method=request.POST.get("method") or (req.payload or {}).get("method") or "bank",
                    reference=request.POST.get("reference") or "",
                    paid_at=paid_at,
                )
                messages.success(
                    request,
                    _(
                        "Settlement qeydə alındı: %(amt)s · ref %(ref)s · JE %(je)s (unposted)."
                    )
                    % {
                        "amt": pay.amount,
                        "ref": pay.reference or "—",
                        "je": pay.journal_entry.code if pay.journal_entry_id else "—",
                    },
                )
            elif action == "cancel_pay_auth":
                req = get_object_or_404(
                    ApprovalRequest,
                    pk=request.POST.get("approval_id"),
                    workflow_code=WF_SUPPLIER_PAYMENT,
                )
                SupplierInvoiceService.cancel_payment_authorization(
                    req,
                    actor=request.user,
                    reason=request.POST.get("reason") or "",
                )
                messages.info(request, _("Ödəniş icazəsi ləğv edildi — rezerv buraxıldı."))
            elif action == "void":
                SupplierInvoiceService.void_supplier_invoice(inv, actor=request.user)
                messages.success(request, _("Void — rezerv buraxıldı (uyğun olduqda)."))
            else:
                messages.error(request, _("Naməlum əməliyyat."))
        except (DomainError, ValueError) as exc:
            messages.error(request, str(exc))
        return redirect("finance:payable_detail", code=inv.code)
