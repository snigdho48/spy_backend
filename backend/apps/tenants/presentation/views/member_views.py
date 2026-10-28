from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.application.services.auth_service import AuthenticationService
from apps.tenants.application.services.member_service import MemberService
from apps.tenants.presentation.serializers.member_serializers import (
    ChangeRoleSerializer,
    InviteCreateSerializer,
    InviteTokenSerializer,
)
from apps.tenants.presentation.views.subscription_views import TenantMixin
from core.domain.exceptions import EntityNotFoundError


class MemberListView(TenantMixin, APIView):
    def get(self, request):
        tenant = self.get_tenant()
        members = MemberService().list_members(actor=request.user, tenant=tenant)
        return Response({"members": members})


class MemberDetailView(TenantMixin, APIView):
    def patch(self, request, membership_id):
        serializer = ChangeRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = self.get_tenant()
        member = MemberService().change_role(
            actor=request.user,
            tenant=tenant,
            membership_id=membership_id,
            new_role=serializer.validated_data["role"],
        )
        return Response({"member": member})

    def delete(self, request, membership_id):
        tenant = self.get_tenant()
        MemberService().remove_member(
            actor=request.user,
            tenant=tenant,
            membership_id=membership_id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class InviteListCreateView(TenantMixin, APIView):
    def get(self, request):
        tenant = self.get_tenant()
        invites = MemberService().list_pending_invites(
            actor=request.user, tenant=tenant
        )
        return Response({"invites": invites})

    def post(self, request):
        serializer = InviteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = self.get_tenant()
        invite = MemberService().invite(
            actor=request.user,
            tenant=tenant,
            email=serializer.validated_data["email"],
            role=serializer.validated_data["role"],
        )
        return Response({"invite": invite}, status=status.HTTP_201_CREATED)


class InviteRevokeView(TenantMixin, APIView):
    def delete(self, request, invite_id):
        tenant = self.get_tenant()
        MemberService().revoke_invite(
            actor=request.user, tenant=tenant, invite_id=invite_id
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class InviteAcceptView(APIView):
    def post(self, request):
        serializer = InviteTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = MemberService().accept_invite(
            user=request.user,
            raw_token=serializer.validated_data["token"],
        )
        return Response(result)


class InviteDeclineView(APIView):
    def post(self, request):
        serializer = InviteTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        MemberService().decline_invite(
            user=request.user,
            raw_token=serializer.validated_data["token"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
