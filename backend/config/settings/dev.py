import os

from .base import *  # noqa: F403

DEBUG = True

# Dev conveniences only (base.py is env-driven and strict).
# Always allow the local/emulator/ngrok hosts even if .env ALLOWED_HOSTS is narrower.
ALLOWED_HOSTS = list(  # noqa: F405
    dict.fromkeys(
        [*ALLOWED_HOSTS, "localhost", "127.0.0.1", "10.0.2.2", ".ngrok-free.app"]  # noqa: F405
    )
)
CORS_ALLOW_ALL_ORIGINS = True

INSTALLED_APPS += [  # noqa: F405
    # Dev tools can be added here
]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Local dev without Docker: MySQL only (no Redis required).
USE_REDIS = os.environ.get("USE_REDIS", "false").lower() in ("true", "1", "yes")

if not USE_REDIS:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
