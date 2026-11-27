from django.urls import path

from apps.finance import views

app_name = "finance"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("charges/", views.ChargesView.as_view(), name="charges"),
    path("invoices/", views.InvoicesView.as_view(), name="invoices"),
    path("invoices/export.xlsx", views.InvoiceExportView.as_view(), name="invoices_export"),
    path("invoices/<str:code>/", views.InvoiceDetailView.as_view(), name="invoice_detail"),
    path("payments/", views.PaymentsView.as_view(), name="payments"),
    path(
        "payment-evidence/",
        views.PaymentEvidenceQueueView.as_view(),
        name="payment_evidence",
    ),
    path(
        "documents/<int:pk>/download/",
        views.FinanceDocumentDownloadView.as_view(),
        name="document_download",
    ),
    path("payables/", views.PayablesView.as_view(), name="payables"),
    path("payables/new/", views.PayableCreateView.as_view(), name="payable_create"),
    path("payables/<str:code>/", views.PayableDetailView.as_view(), name="payable_detail"),
    path("aging/", views.AgingView.as_view(), name="aging"),
    path("aging/export.xlsx", views.AgingExportView.as_view(), name="aging_export"),
    path("accounts/", views.AccountsView.as_view(), name="accounts"),
    path("journals/", views.JournalsView.as_view(), name="journals"),
    path("journals/new/", views.JournalCreateView.as_view(), name="journal_create"),
    path("journals/<str:code>/", views.JournalDetailView.as_view(), name="journal_detail"),
    path("trial-balance/", views.TrialBalanceView.as_view(), name="trial_balance"),
    path(
        "trial-balance/export.xlsx",
        views.TrialBalanceExportView.as_view(),
        name="trial_balance_export",
    ),
    path("periods/", views.PeriodsView.as_view(), name="periods"),
    path(
        "building-equipment/",
        views.BuildingEquipmentListView.as_view(),
        name="building_equipment",
    ),
    path(
        "building-inventory/",
        views.BuildingInventoryListView.as_view(),
        name="building_inventory",
    ),
]
