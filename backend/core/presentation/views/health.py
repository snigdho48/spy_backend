from django.db import connection
from django.core.cache import cache
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        db_ok = False
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            db_ok = True
        except Exception:
            pass

        redis_ok = cache.set("health_check", "1", timeout=5) is not False
        try:
            cache.get("health_check")
            redis_ok = True
        except Exception:
            redis_ok = False

        status_val = "healthy" if db_ok and redis_ok else "degraded"
        return Response(
            {
                "status": status_val,
                "db": "ok" if db_ok else "error",
                "redis": "ok" if redis_ok else "error",
                "version": "1.0.0",
            }
        )


class LiveView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "alive"})


class ReadyView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            return Response({"status": "not_ready"}, status=503)
        return Response({"status": "ready"})
