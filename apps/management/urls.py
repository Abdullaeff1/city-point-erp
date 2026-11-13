"""Legacy /management/ → ERP redirects (bookmark uyğunluğu)."""

from django.urls import path
from django.views.generic import RedirectView

app_name = "management"

urlpatterns = [
    path(
        "",
        RedirectView.as_view(pattern_name="erp:dashboard", permanent=False),
        name="home",
    ),
    path(
        "approvals/",
        RedirectView.as_view(pattern_name="erp:approvals", permanent=False),
        name="approvals",
    ),
    path(
        "crm/offers/",
        RedirectView.as_view(pattern_name="erp:crm_offers", permanent=False),
        name="crm_offers",
    ),
    path(
        "crm/offers/<int:pk>/",
        RedirectView.as_view(pattern_name="erp:crm_offer_detail", permanent=False),
        name="crm_offer_detail",
    ),
    path(
        "crm/reports/",
        RedirectView.as_view(pattern_name="erp:crm_reports", permanent=False),
        name="crm_reports",
    ),
    path(
        "payments/",
        RedirectView.as_view(pattern_name="erp:payment_approvals", permanent=False),
        name="payments",
    ),
    path(
        "aging/",
        RedirectView.as_view(pattern_name="erp:ar_aging", permanent=False),
        name="aging",
    ),
    path(
        "sla/",
        RedirectView.as_view(pattern_name="erp:sla_report", permanent=False),
        name="sla",
    ),
    path(
        "periods/",
        RedirectView.as_view(pattern_name="erp:accounting_periods", permanent=False),
        name="periods",
    ),
]
