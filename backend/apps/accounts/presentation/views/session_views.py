from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.application.services.session_service import SessionService


class SessionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Clients may pass the current refresh via query or X-Refresh-Token so we
        # can mark is_current without requiring a body on GET.
        refresh = request.query_params.get("refresh") or request.headers.get(
            "X-Refresh-Token"
        )
        current_jti = SessionService().jti_from_refresh(refresh)
        sessions = SessionService().list_sessions(
            user=request.user, current_jti=current_jti
        )
        return Response({"sessions": sessions})


class SessionRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, session_id):
        SessionService().revoke(user=request.user, session_id=session_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionRevokeOthersView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.data.get("refresh")
        current_jti = SessionService().jti_from_refresh(refresh)
        count = SessionService().revoke_others(user=request.user, current_jti=current_jti)
        return Response({"revoked": count})


class TrackingTokenRefreshView(TokenRefreshView):
    """Rotate refresh tokens and keep RefreshTokenRecord in sync."""

    def post(self, request, *args, **kwargs):
        old_refresh = request.data.get("refresh")
        old_jti = SessionService().jti_from_refresh(old_refresh)
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200 and old_jti:
            new_refresh_str = response.data.get("refresh") or old_refresh
            try:
                from rest_framework_simplejwt.tokens import RefreshToken

                new_refresh = RefreshToken(new_refresh_str)
                SessionService().touch_refresh(
                    old_jti=old_jti,
                    new_refresh=new_refresh,
                    ip_address=(
                        request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
                        or request.META.get("REMOTE_ADDR")
                    ),
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                )
            except Exception:
                pass
        return response
