from django.urls import path

from apps.tenants.presentation.views.member_views import (
    InviteAcceptView,
    InviteDeclineView,
    InviteListCreateView,
    InviteRevokeView,
    MemberDetailView,
    MemberListView,
)

urlpatterns = [
    path("members/", MemberListView.as_view(), name="tenant-members"),
    path(
        "members/<uuid:membership_id>/",
        MemberDetailView.as_view(),
        name="tenant-member-detail",
    ),
    path("invites/", InviteListCreateView.as_view(), name="tenant-invites"),
    path(
        "invites/<uuid:invite_id>/",
        InviteRevokeView.as_view(),
        name="tenant-invite-revoke",
    ),
    path("invites/accept/", InviteAcceptView.as_view(), name="tenant-invite-accept"),
    path("invites/decline/", InviteDeclineView.as_view(), name="tenant-invite-decline"),
]
