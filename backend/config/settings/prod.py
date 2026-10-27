from .base import *  # noqa: F403

DEBUG = False

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Comma-separated origins, e.g. https://spy.way2points.com (required for admin
# POSTs once the tunnel terminates TLS).
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")  # noqa: F405
    if origin.strip()
]

# Optional dedicated JWT HMAC key. Empty keeps simplejwt's SECRET_KEY default.
_jwt_signing_key = os.environ.get("JWT_SIGNING_KEY", "").strip()  # noqa: F405
if _jwt_signing_key:
    SIMPLE_JWT["SIGNING_KEY"] = _jwt_signing_key  # noqa: F405

SENTRY_DSN = os.environ.get("SENTRY_DSN")  # noqa: F405
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )
