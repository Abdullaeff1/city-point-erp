from django.urls import path

from apps.api import views, views_reception

app_name = "api"

urlpatterns = [
    path("v1/public/spaces/", views.public_spaces, name="public_spaces"),
    path("v1/public/leads/", views.public_leads, name="public_leads"),
    path("reception/visits/", views_reception.reception_visits, name="reception_visits"),
    path("reception/visits/<int:pk>/", views_reception.reception_visit_detail, name="reception_visit_detail"),
    path(
        "reception/visits/<int:pk>/check-in/",
        views_reception.reception_visit_check_in,
        name="reception_visit_check_in",
    ),
    path(
        "reception/visits/<int:pk>/check-out/",
        views_reception.reception_visit_check_out,
        name="reception_visit_check_out",
    ),
    path(
        "reception/visits/<int:pk>/cancel/",
        views_reception.reception_visit_cancel,
        name="reception_visit_cancel",
    ),
    path("reception/guests/search/", views_reception.reception_guest_search, name="reception_guest_search"),
    path("reception/today/", views_reception.reception_today, name="reception_today"),
]
