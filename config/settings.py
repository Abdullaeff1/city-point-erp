import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

for env_path in (
    BASE_DIR / "bin" / "dev" / ".env",
    BASE_DIR / "bin" / "prod" / ".env",
    BASE_DIR / ".env",
):
    if env_path.exists():
        load_dotenv(env_path)
        break

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "unsafe-dev-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
CP_ENV = os.environ.get("CP_ENV", "development").strip().lower()  # development | staging | production
CP_OFFLINE = os.environ.get("CP_OFFLINE", "0") == "1"  # LAN/air-gapped: no Internet assumed
if not DEBUG and (not SECRET_KEY or SECRET_KEY == "unsafe-dev-key"):
    raise RuntimeError("DJANGO_SECRET_KEY must be set to a strong value when DJANGO_DEBUG=0")
if CP_ENV == "production" and DEBUG:
    raise RuntimeError("CP_ENV=production requires DJANGO_DEBUG=0")
if CP_ENV == "production" and os.environ.get("SEED_DEMO", "0") == "1":
    raise RuntimeError("SEED_DEMO must be 0 when CP_ENV=production")
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core.apps.CoreConfig",
    "apps.accounts.apps.AccountsConfig",
    "apps.parties.apps.PartiesConfig",
    "apps.property.apps.PropertyConfig",
    "apps.residents.apps.ResidentsConfig",
    "apps.reception.apps.ReceptionConfig",
    "apps.tickets.apps.TicketsConfig",
    "apps.comms.apps.CommsConfig",
    "apps.documents.apps.DocumentsConfig",
    "apps.audit.apps.AuditConfig",
    "apps.rbac.apps.RbacConfig",
    "apps.workflows.apps.WorkflowsConfig",
    "apps.integrations.apps.IntegrationsConfig",
    "apps.leases.apps.LeasesConfig",
    "apps.crm.apps.CrmConfig",
    "apps.maintenance.apps.MaintenanceConfig",
    "apps.warehouse.apps.WarehouseConfig",
    "apps.procurement.apps.ProcurementConfig",
    "apps.billing.apps.BillingConfig",
    "apps.accounting.apps.AccountingConfig",
    "apps.api.apps.ApiConfig",
    "apps.portal.apps.PortalConfig",
    "apps.security.apps.SecurityConfig",
    "apps.erp.apps.ErpConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.MustSetPasswordMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.accounts.context_processors.role_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "citypoint"),
        "USER": os.environ.get("POSTGRES_USER", "citypoint"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "citypoint"),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "http://localhost:3001,http://127.0.0.1:3001,http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if origin.strip()
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Session: 8h idle-ish absolute age; browser close still ends session cookie unless SESSION_EXPIRE_AT_BROWSER_CLOSE
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_COOKIE_AGE", str(8 * 60 * 60)))
SESSION_EXPIRE_AT_BROWSER_CLOSE = os.environ.get("SESSION_EXPIRE_AT_BROWSER_CLOSE", "0") == "1"
SESSION_SAVE_EVERY_REQUEST = os.environ.get("SESSION_SAVE_EVERY_REQUEST", "1") == "1"

LANGUAGE_CODE = "az"
LANGUAGES = [
    ("az", "Azərbaycan dili"),
    ("en", "English"),
    ("ru", "Русский"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Asia/Baku"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "post_login"
LOGOUT_REDIRECT_URL = "login"

# Email (invite + password reset). Console backend for local/dev.
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@citypoint.az")

# Air-gapped: allow file-based outbox instead of Internet SMTP.
# Ops can copy invite URLs from var/mail_outbox or use internal LAN Exchange.
if CP_OFFLINE and not os.environ.get("EMAIL_BACKEND"):
    EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
    EMAIL_FILE_PATH = os.environ.get("EMAIL_FILE_PATH", str(BASE_DIR / "var" / "mail_outbox"))
elif CP_ENV in {"production", "staging"} and "console.EmailBackend" in EMAIL_BACKEND and not CP_OFFLINE:
    raise RuntimeError(f"CP_ENV={CP_ENV} requires a real EMAIL_BACKEND (not console), or set CP_OFFLINE=1")

# Production HTTPS hardening (enable when behind TLS reverse proxy)
if not DEBUG:
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "1") == "1"
    CSRF_COOKIE_SECURE = os.environ.get("CSRF_COOKIE_SECURE", "1") == "1"
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "0") == "1"
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
    if os.environ.get("SECURE_PROXY_SSL_HEADER", ""):
        # e.g. SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https
        header, value = os.environ["SECURE_PROXY_SSL_HEADER"].split(",", 1)
        SECURE_PROXY_SSL_HEADER = (header.strip(), value.strip())
