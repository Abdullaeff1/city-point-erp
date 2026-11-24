"""Finance home KPIs and work-queue counts (reconcile to filtered destinations)."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting.coa import code_for
from apps.accounting.models import Account, JournalEntry, JournalLine
from apps.accounting.services import seed_minimal_coa
from apps.billing.models import (
    Invoice,
    InvoiceStatus,
    Payment,
    SupplierInvoice,
    SupplierInvoiceStatus,
    SupplierPayment,
)
from apps.billing.services import invoice_balance, mark_overdue_invoices
from apps.finance.ap_services import WF_SUPPLIER_PAYMENT, supplier_payment_queue_invoice_ids
from apps.workflows.models import ApprovalRequest, ApprovalStatus

WF_PAYMENT = "finance.payment"


def pending_payment_approvals_qs():
    return ApprovalRequest.objects.filter(
        workflow_code=WF_PAYMENT, status=ApprovalStatus.PENDING
    )


def draft_invoices_qs():
    return Invoice.objects.filter(status=InvoiceStatus.DRAFT)


def unposted_journals_qs():
    return JournalEntry.objects.filter(posted=False)


def hold_supplier_invoices_qs():
    return SupplierInvoice.objects.filter(status=SupplierInvoiceStatus.HOLD)


def confirmed_payments_month_qs(*, today=None):
    today = today or timezone.localdate()
    return Payment.objects.filter(paid_at__year=today.year, paid_at__month=today.month)


def build_dashboard(*, today=None) -> dict:
    today = today or timezone.localdate()
    mark_overdue_invoices()
    open_inv = Invoice.objects.filter(
        status__in=(InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE)
    )
    overdue_inv = Invoice.objects.filter(status=InvoiceStatus.OVERDUE)
    draft_qs = draft_invoices_qs()
    pending_qs = pending_payment_approvals_qs()
    unposted_qs = unposted_journals_qs()
    hold_qs = hold_supplier_invoices_qs()
    paid_month_qs = confirmed_payments_month_qs(today=today)
    ap_pending_n = ApprovalRequest.objects.filter(
        workflow_code=WF_SUPPLIER_PAYMENT, status=ApprovalStatus.PENDING
    ).count()
    ap_await_n = len(supplier_payment_queue_invoice_ids(queue="awaiting_settle"))
    ap_unposted_n = SupplierPayment.objects.filter(journal_entry__posted=False).count()

    ar_total = sum(
        (invoice_balance(i) for i in open_inv.select_related("party")), Decimal("0")
    )
    overdue_total = sum(
        (invoice_balance(i) for i in overdue_inv.select_related("party")), Decimal("0")
    )
    cash_month = paid_month_qs.aggregate(s=Sum("amount"))["s"] or Decimal("0")

    posted_ar = None
    posted_ar_label = _("Mövcud deyil")
    try:
        seed_minimal_coa()
        ar_code = code_for("ar")
        if Account.objects.filter(code=ar_code, is_active=True).exists():
            debit = (
                JournalLine.objects.filter(
                    entry__posted=True, account__code=ar_code
                ).aggregate(s=Sum("debit"))["s"]
                or Decimal("0")
            )
            credit = (
                JournalLine.objects.filter(
                    entry__posted=True, account__code=ar_code
                ).aggregate(s=Sum("credit"))["s"]
                or Decimal("0")
            )
            posted_ar = debit - credit
            posted_ar_label = f"{posted_ar} AZN"
    except Exception:  # noqa: BLE001
        posted_ar = None
        posted_ar_label = _("Mövcud deyil")

    queue = [
        {
            "key": "draft",
            "label": _("Draft fakturalar"),
            "count": draft_qs.count(),
            "url": reverse("finance:invoices") + "?status=draft",
        },
        {
            "key": "pending_approvals",
            "label": _("Ödəniş təsdiqi gözləyənlər"),
            "count": pending_qs.count(),
            "url": reverse("finance:payments") + "?pending=1",
        },
        {
            "key": "unposted_je",
            "label": _("Unposted JE"),
            "count": unposted_qs.count(),
            "url": reverse("finance:journals") + "?posted=0",
        },
        {
            "key": "ap_hold",
            "label": _("AP HOLD"),
            "count": hold_qs.count(),
            "url": reverse("finance:payables") + "?status=hold",
        },
        {
            "key": "ap_pending_pay",
            "label": _("AP ödəniş təsdiqi"),
            "count": ap_pending_n,
            "url": reverse("finance:payables") + "?queue=pending_approval",
        },
        {
            "key": "ap_await_settle",
            "label": _("AP settlement gözləyən"),
            "count": ap_await_n,
            "url": reverse("finance:payables") + "?queue=awaiting_settle",
        },
        {
            "key": "ap_unposted_pay",
            "label": _("AP ödəniş unposted JE"),
            "count": ap_unposted_n,
            "url": reverse("finance:payables") + "?queue=unposted_settle",
        },
    ]

    indicators = [
        {
            "label": _("Əməliyyat AR"),
            "value": f"{ar_total}",
            "meta": f"AZN · {today.isoformat()}",
            "url": reverse("finance:aging"),
        },
        {
            "label": _("Gecikmiş"),
            "value": f"{overdue_inv.count()}",
            "meta": f"{overdue_total} AZN",
            "url": reverse("finance:invoices") + "?status=overdue",
        },
        {
            "label": _("Bu ay nağd/bank daxilolma"),
            "value": f"{cash_month}",
            "meta": "AZN",
            "url": reverse("finance:payments"),
        },
        {
            "label": _("Posted GL AR"),
            "value": posted_ar_label if posted_ar is None else f"{posted_ar}",
            "meta": "AZN" if posted_ar is not None else _("Etibarlı mənbə yoxdur / TB"),
            "url": reverse("finance:trial_balance") if posted_ar is not None else "",
        },
    ]

    return {
        "as_of": today,
        "queue": queue,
        "indicators": indicators,
        "draft_count": draft_qs.count(),
        "pending_approvals_count": pending_qs.count(),
        "unposted_je": unposted_qs.count(),
        "ap_hold_count": hold_qs.count(),
        "ar_total": ar_total,
        "overdue_count": overdue_inv.count(),
        "overdue_total": overdue_total,
        "cash_month": cash_month,
        "paid_month_count": paid_month_qs.count(),
        "posted_ar": posted_ar,
    }
