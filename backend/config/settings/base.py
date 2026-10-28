"""Base Django settings shared across environments."""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-dev-only-change-in-production",
)

DEBUG = os.environ.get("DEBUG", "False").lower() in ("true", "1", "yes")

def _csv_env(name: str, default: str = "") -> list[str]:
    """Parse a comma-separated environment variable into a clean list."""
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


# Env-driven (CSV). Defaults cover local dev: localhost, Android emulator host
# alias (10.0.2.2) and ngrok free tunnels. Set ALLOWED_HOSTS explicitly in prod.
ALLOWED_HOSTS = _csv_env(
    "ALLOWED_HOSTS", "localhost,127.0.0.1,10.0.2.2,.ngrok-free.app"
)

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "channels",
    # Local apps
    "core",
    "apps.tenants",
    "apps.accounts",
    "apps.devices",
    "apps.events",
    "apps.alerts",
    "apps.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.request_id.RequestIdMiddleware",
    "core.middleware.audit.AuditContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# --- Prometheus metrics (django-prometheus) ---
# Guarded so a checkout that has not reinstalled requirements still boots (e.g.
# the USE_REDIS=false local setup). When the package is importable we register
# the app and wrap MIDDLEWARE with the Before/After pair, which must be the
# FIRST and LAST middleware per the django-prometheus docs. The DB/cache
# backends are intentionally NOT swapped, so this is safe for prod and for the
# local in-memory cache/channel-layer setup.
try:
    import django_prometheus  # noqa: F401

    PROMETHEUS_METRICS_ENABLED = True
    if "django_prometheus" not in INSTALLED_APPS:
        INSTALLED_APPS.append("django_prometheus")
    if "django_prometheus.middleware.PrometheusBeforeMiddleware" not in MIDDLEWARE:
        MIDDLEWARE.insert(0, "django_prometheus.middleware.PrometheusBeforeMiddleware")
        MIDDLEWARE.append("django_prometheus.middleware.PrometheusAfterMiddleware")
except ImportError:  # pragma: no cover - exporter is optional in minimal envs
    PROMETHEUS_METRICS_ENABLED = False


ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_USER_MODEL = "accounts.User"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("MYSQL_DATABASE", "spylove"),
        "USER": os.environ.get("MYSQL_USER", "spylove"),
        "PASSWORD": os.environ.get("MYSQL_PASSWORD", "spylove"),
        "HOST": os.environ.get("MYSQL_HOST", "localhost"),
        "PORT": os.environ.get("MYSQL_PORT", "3306"),
        "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60")),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
            "IGNORE_EXCEPTIONS": True,
        },
        "KEY_PREFIX": "spylove",
    }
}

# Celery
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300

# Periodic retention purge (requires a celery beat process, or run the
# `purge_expired_events` management command via cron — preferred on lean hosts).
CELERY_BEAT_SCHEDULE = {
    "purge-expired-events-hourly": {
        "task": "events.purge_expired_events",
        "schedule": 3600.0,
        "kwargs": {"chunk_size": 500},
    },
}

# Fernet key (url-safe base64, 32 bytes) for application-level field encryption.
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Empty = encryption disabled (dev only). Production fails closed — see prod.py.
FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY", "").strip()

# Channels
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.environ.get("REDIS_URL", "redis://localhost:6379/0")],
        },
    },
}

# DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "core.presentation.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/minute",
        "user": "100/minute",
        "auth": "10/minute",
        "events": "1000/minute",
    },
    "EXCEPTION_HANDLER": "core.presentation.exceptions.custom_exception_handler",
}

# JWT
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(os.environ.get("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", "15"))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(os.environ.get("JWT_REFRESH_TOKEN_LIFETIME_DAYS", "7"))
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Spy Love API",
    "DESCRIPTION": "Consent-based device monitoring platform",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# Env-driven (CSV of full origins, e.g. https://app.example.com). Empty = no
# cross-origin browser access. Dev-only allow-all lives in settings/dev.py.
CORS_ALLOWED_ORIGINS = _csv_env("CORS_ALLOWED_ORIGINS", "")

# Security headers (production overrides in prod.py)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Consent
CONSENT_VERSION = "1.0.0"
VALID_CONSENT_SCOPES = frozenset({
    "location",
    "battery",
    "network",
    "app_usage",
    "device_info",
    "notifications",
    "call_log",
    "sms",
    "messaging",
    "sim",
    "screen",
    "contacts",
    "telemetry",
    "sos",
})

# Human-facing catalog for the consent scopes above: a clear label and
# description per scope, surfaced at pair-complete and in consent UIs. The
# Flutter mirror lives in `spy_love/lib/app/modules/pairing/models/consent_scope.dart`.
CONSENT_SCOPE_CATALOG = {
    "location": {"label": "Location", "description": "Live location and location history."},
    "battery": {"label": "Battery", "description": "Battery level and charging state."},
    "network": {"label": "Network", "description": "Connected Wi-Fi/mobile network info."},
    "app_usage": {"label": "App usage", "description": "Which apps are used and for how long."},
    "device_info": {"label": "Device info", "description": "Model, OS version and device status."},
    "notifications": {"label": "Notifications", "description": "Incoming notification summaries."},
    "call_log": {"label": "Call log", "description": "Recent call history (no audio)."},
    "sms": {"label": "SMS", "description": "SMS metadata and flagged-keyword matches."},
    "messaging": {"label": "Messaging", "description": "Messaging-app metadata and flagged matches."},
    "sim": {"label": "SIM", "description": "SIM card and carrier changes."},
    "screen": {
        "label": "Live screen",
        "description": (
            "Allow a monitor to view this device's screen live, on request. "
            "Requires an on-device capture grant and shows a persistent sharing "
            "indicator; can be revoked at any time."
        ),
    },
    "contacts": {
        "label": "Contacts",
        "description": "Address-book names, phone numbers, and emails (snapshot).",
    },
    "telemetry": {
        "label": "Device telemetry",
        "description": "Battery, charging, network type, storage and memory status.",
    },
    "sos": {
        "label": "SOS / panic",
        "description": "Allow this device to emit high-priority SOS / panic alerts.",
    },
}

# Pairing
PAIRING_CODE_TTL_SECONDS = 600

# Google Sign-In â€” comma-separated OAuth client IDs (web + Android + iOS)
GOOGLE_CLIENT_IDS = [
    cid.strip()
    for cid in os.environ.get("GOOGLE_CLIENT_IDS", "").split(",")
    if cid.strip()
]

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "sensitive_data": {
            "()": "core.logging_filters.SensitiveDataFilter",
        },
    },
    "formatters": {
        "json": {
            "format": '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
        },
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["sensitive_data"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {"level": "INFO"},
        # Default INFO; DEBUG only when DJANGO_LOG_LEVEL=DEBUG (never in prod).
        "apps": {"level": os.environ.get("DJANGO_LOG_LEVEL", "INFO").upper()},
    },
}


# Firebase Cloud Messaging (HTTP v1). Path to a Google service-account JSON.
# When unset / missing the FCM client is a no-op (safe for local & tests).
FCM_CREDENTIALS_PATH = os.environ.get("FCM_CREDENTIALS_PATH", "").strip()

# Low-battery alert threshold (percent). Fires when battery_pct <= this AND not charging.
LOW_BATTERY_THRESHOLD_PCT = int(os.environ.get("LOW_BATTERY_THRESHOLD_PCT", "15"))

# Public app origin used to build shareable invite links (no trailing slash).
APP_PUBLIC_URL = os.environ.get("APP_PUBLIC_URL", "").rstrip("/")
