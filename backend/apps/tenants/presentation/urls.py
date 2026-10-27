from django.urls import path

from apps.tenants.presentation.views.subscription_views import (
    CurrentSubscriptionView,
    PlanListView,
    SubscribeView,
    WorkspaceCreateView,
)

urlpatterns = [
    path("plans/", PlanListView.as_view(), name="subscription-plans"),
    path("current/", CurrentSubscriptionView.as_view(), name="subscription-current"),
    path("subscribe/", SubscribeView.as_view(), name="subscription-subscribe"),
    path("workspaces/", WorkspaceCreateView.as_view(), name="workspace-create"),
]
