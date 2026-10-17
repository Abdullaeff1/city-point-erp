from django.urls import path

from apps.security import views, views_plans

app_name = "security"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("plans/", views_plans.PlanListView.as_view(), name="plans"),
    path("plans/upload/", views_plans.PlanUploadView.as_view(), name="plan_upload"),
    path("plans/<int:pk>/", views_plans.PlanDetailView.as_view(), name="plan_detail"),
    path(
        "plans/<int:pk>/revision/",
        views_plans.PlanRevisionUploadView.as_view(),
        name="plan_revision_upload",
    ),
    path(
        "plans/<int:pk>/revisions/<int:revision_id>/activate/",
        views_plans.PlanRevisionActivateView.as_view(),
        name="plan_revision_activate",
    ),
    path(
        "plans/<int:pk>/revisions/<int:revision_id>/retry/",
        views_plans.PlanRevisionRetryView.as_view(),
        name="plan_revision_retry",
    ),
    path(
        "plans/<int:pk>/revisions/<int:revision_id>/svg/",
        views_plans.PlanSvgView.as_view(),
        name="plan_svg",
    ),
    path(
        "plans/<int:pk>/revisions/<int:revision_id>/download/",
        views_plans.PlanSourceDownloadView.as_view(),
        name="plan_source_download",
    ),
    path(
        "plans/<int:pk>/revisions/<int:revision_id>/pins/",
        views_plans.PlanPinUpsertView.as_view(),
        name="plan_pin_upsert",
    ),
    path(
        "plans/<int:pk>/revisions/<int:revision_id>/pins/<int:pin_id>/delete/",
        views_plans.PlanPinDeleteView.as_view(),
        name="plan_pin_delete",
    ),
    path("devices/", views_plans.DeviceListView.as_view(), name="devices"),
    path("devices/create/", views_plans.DeviceCreateView.as_view(), name="device_create"),
    path("devices/<int:pk>/update/", views_plans.DeviceUpdateView.as_view(), name="device_update"),
    path(
        "devices/<int:pk>/deactivate/",
        views_plans.DeviceDeactivateView.as_view(),
        name="device_deactivate",
    ),
    path("events/feed/", views.EventsFeedView.as_view(), name="events_feed"),
    path("people-inside/", views.PeopleInsideView.as_view(), name="people_inside"),
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
    path(
        "companies/<int:pk>/access/export/",
        views.CompanyAccessExportView.as_view(),
        name="company_access_export",
    ),
    path(
        "companies/<int:pk>/employees/<int:employee_pk>/access/export/",
        views.CompanyAccessExportView.as_view(),
        name="employee_access_export",
    ),
    path("guests/", views.GuestsView.as_view(), name="guests"),
    path("employees/", views.EmployeeListView.as_view(), name="employees"),
    path("employees/<int:pk>/access/", views.EmployeeAccessDetailView.as_view(), name="employee_access"),
    path("tickets/", views.TicketListView.as_view(), name="tickets"),
    path("tickets/<str:code>/", views.TicketDetailView.as_view(), name="ticket_detail"),
]