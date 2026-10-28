from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from core.presentation.views.health import HealthView, LiveView, ReadyView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", HealthView.as_view(), name="health"),
    path("health/live/", LiveView.as_view(), name="health-live"),
    path("health/ready/", ReadyView.as_view(), name="health-ready"),
    path("api/v1/auth/", include("apps.accounts.presentation.urls")),
    path("api/v1/subscriptions/", include("apps.tenants.presentation.urls")),
    path("api/v1/tenants/", include("apps.tenants.presentation.member_urls")),
    path("api/v1/devices/", include("apps.devices.presentation.urls")),
    path("api/v1/events/", include("apps.events.presentation.urls")),
    path("api/v1/alerts/", include("apps.alerts.presentation.urls")),
    path("api/v1/audit/", include("apps.audit.presentation.urls")),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

from django.conf import settings  # noqa: E402

# Prometheus exporter at /metrics (guarded; enabled in base settings only when
# django-prometheus is installed). Exposes Prometheus text format for scraping.
if getattr(settings, "PROMETHEUS_METRICS_ENABLED", False):
    urlpatterns.append(path("", include("django_prometheus.urls")))
