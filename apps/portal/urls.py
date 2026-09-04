from django.urls import path

from apps.portal import views

app_name = "portal"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("spaces/", views.SpacesView.as_view(), name="spaces"),
    path("requests/new/", views.RequestCreateView.as_view(), name="request_new"),
    path("requests/active/", views.RequestListView.as_view(), {"scope": "active"}, name="requests_active"),
    path("requests/history/", views.RequestListView.as_view(), {"scope": "history"}, name="requests_history"),
    path("requests/<str:code>/", views.RequestDetailView.as_view(), name="request_detail"),
    path("alerts/", views.AlertsView.as_view(), name="alerts"),
    path("employees/access/", views.EmployeeAccessView.as_view(), name="employees"),
    path("guests/", views.GuestsView.as_view(), name="guests"),
    path("announcements/", views.AnnouncementsView.as_view(), name="announcements"),
    path("documents/", views.DocumentsView.as_view(), name="documents"),
]
