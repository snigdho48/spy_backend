from django.urls import path

from apps.audit.presentation.views.audit_views import AuditLogListView

urlpatterns = [
    path("", AuditLogListView.as_view(), name="audit-list"),
]
