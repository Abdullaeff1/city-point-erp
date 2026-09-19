from django.urls import path

from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("invite/<str:token>/", views.invite_accept, name="invite_accept"),
    path("force-password/", views.force_set_password, name="force_set_password"),
    path("password-reset/", views.PortalPasswordResetView.as_view(), name="password_reset"),
    path("password-reset/done/", views.password_reset_done, name="password_reset_done"),
    path(
        "password-reset/<uidb64>/<token>/",
        views.PortalPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path("password-reset/complete/", views.password_reset_complete, name="password_reset_complete"),
]
