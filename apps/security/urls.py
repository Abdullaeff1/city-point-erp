from django.urls import path

from apps.security import views

app_name = "security"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("alerts/", views.AlertListView.as_view(), name="alerts"),
    path("alerts/rapid/", views.AlertListView.as_view(), {"kind": "rapid"}, name="alerts_rapid"),
    path("alerts/shaft/", views.AlertListView.as_view(), {"kind": "shaft"}, name="alerts_shaft"),
    path("alerts/rapid/<int:pk>/", views.AlertDetailView.as_view(), name="alert_detail"),
    path("alerts/rapid/<int:pk>/ack/", views.AlertAcknowledgeView.as_view(), name="alert_ack"),
    path("alerts/shaft/<int:pk>/", views.ShaftAlertDetailView.as_view(), name="shaft_alert_detail"),
    path("alerts/shaft/<int:pk>/ack/", views.ShaftAlertAcknowledgeView.as_view(), name="shaft_alert_ack"),
    # Legacy rapid alert detail URLs
    path("alerts/<int:pk>/", views.AlertDetailView.as_view(), name="alert_detail_legacy"),
    path("alerts/<int:pk>/ack/", views.AlertAcknowledgeView.as_view(), name="alert_ack_legacy"),
    path("companies/", views.CompanyListView.as_view(), name="companies"),
    path("companies/<int:pk>/", views.CompanyEmployeesView.as_view(), name="company_employees"),
    path("employees/<int:pk>/access/", views.EmployeeAccessDetailView.as_view(), name="employee_access"),
    path("tickets/", views.TicketListView.as_view(), name="tickets"),
    path("tickets/<str:code>/", views.TicketDetailView.as_view(), name="ticket_detail"),
]
