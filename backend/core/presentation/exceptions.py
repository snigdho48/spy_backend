from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from core.domain.exceptions import (
    ConflictError,
    ConsentRequiredError,
    DomainError,
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)

_STATUS_MAP = {
    EntityNotFoundError: status.HTTP_404_NOT_FOUND,
    ValidationError: status.HTTP_400_BAD_REQUEST,
    PermissionDeniedError: status.HTTP_403_FORBIDDEN,
    ConsentRequiredError: status.HTTP_403_FORBIDDEN,
    ConflictError: status.HTTP_409_CONFLICT,
}


def custom_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response(
            {
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                }
            },
            status=_STATUS_MAP.get(type(exc), status.HTTP_400_BAD_REQUEST),
        )

    response = exception_handler(exc, context)
    if response is not None and isinstance(response.data, dict):
        response.data = {
            "error": {
                "code": "api_error",
                "message": response.data.get("detail", str(response.data)),
                "details": response.data,
            }
        }
    return response
