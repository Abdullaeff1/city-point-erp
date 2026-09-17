from django.urls import path

from apps.erp import views

app_name = "erp"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("reception/", views.ReceptionView.as_view(), name="reception"),
    path("reception/<int:pk>/status/", views.ReceptionStatusView.as_view(), name="reception_status"),
    path("reception/guest-lookup/", views.ReceptionGuestLookupView.as_view(), name="reception_guest_lookup"),
    path("reception/export/", views.ReceptionExportView.as_view(), name="reception_export"),
    path("tickets/", views.TicketListView.as_view(), name="tickets"),
    path("tickets/<str:code>/", views.TicketDetailView.as_view(), name="ticket_detail"),
    path("spaces/", views.SpaceListView.as_view(), name="spaces"),
    path("spaces/<str:code>/", views.SpaceDetailView.as_view(), name="space_detail"),
    path("residents/", views.ResidentListView.as_view(), name="residents"),
    path("residents/<slug:slug>/", views.ResidentDetailView.as_view(), name="resident_detail"),
    path("parties/", views.PartyListView.as_view(), name="parties"),
    path("leases/", views.LeaseListView.as_view(), name="leases"),
    path("leases/<str:code>/", views.LeaseDetailView.as_view(), name="lease_detail"),
    path("crm/leads/", views.CrmLeadListView.as_view(), name="crm_leads"),
    path("crm/offers/", views.CrmOfferListView.as_view(), name="crm_offers"),
    path("work-orders/", views.WorkOrderListView.as_view(), name="work_orders"),
    path("warehouse/", views.WarehouseListView.as_view(), name="warehouse"),
    path("procurement/", views.ProcurementListView.as_view(), name="procurement"),
    path("billing/", views.BillingListView.as_view(), name="billing"),
    path("accounting/", views.AccountingListView.as_view(), name="accounting"),
    path("documents/", views.DocumentsView.as_view(), name="documents"),
    path("reports/", views.ReportsView.as_view(), name="reports"),
]
