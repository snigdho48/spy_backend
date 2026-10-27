from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.application.services.keyword_service import KeywordService
from apps.devices.presentation.serializers.keyword_serializers import (
    WatchlistKeywordSerializer,
    WatchlistKeywordWriteSerializer,
)


class KeywordListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = KeywordService().list_for_user(request.user)
        return Response(
            {"results": WatchlistKeywordSerializer(rows, many=True).data}
        )

    def post(self, request):
        serializer = WatchlistKeywordWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = KeywordService().create(
            user=request.user, word=serializer.validated_data["word"]
        )
        return Response(
            WatchlistKeywordSerializer(row).data, status=status.HTTP_201_CREATED
        )


class KeywordDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, keyword_id):
        KeywordService().delete(user=request.user, keyword_id=keyword_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
