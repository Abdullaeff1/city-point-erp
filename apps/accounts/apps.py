from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Hesablar"

    def ready(self):
        from django.contrib import admin

        admin.site.site_header = "City Point"
        admin.site.site_title = "City Point"
        admin.site.index_title = "İdarəetmə"
