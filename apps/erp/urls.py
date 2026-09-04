from django.urls import path

from apps.erp import views

app_name = "erp"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("reception/", views.ReceptionView.as_view(), name="reception"),
    path("reception/<int:pk>/status/", views.ReceptionStatusView.as_view(), name="reception_status"),
    path("tickets/", views.TicketListView.as_view(), name="tickets"),
    path("tickets/<str:code>/", views.TicketDetailView.as_view(), name="ticket_detail"),
    path("spaces/", views.SpaceListView.as_view(), name="spaces"),
    path("spaces/<str:code>/", views.SpaceDetailView.as_view(), name="space_detail"),
    path("residents/", views.ResidentListView.as_view(), name="residents"),
    path("residents/<slug:slug>/", views.ResidentDetailView.as_view(), name="resident_detail"),
    path("documents/", views.DocumentsView.as_view(), name="documents"),
    path("reports/", views.ReportsView.as_view(), name="reports"),
]
