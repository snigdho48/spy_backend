"""Domain-level exceptions — no framework dependencies."""


class DomainError(Exception):
    """Base domain exception."""

    code: str = "domain_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class EntityNotFoundError(DomainError):
    code = "not_found"


class ValidationError(DomainError):
    code = "validation_error"


class PermissionDeniedError(DomainError):
    code = "forbidden"


class ConsentRequiredError(DomainError):
    code = "consent_required"


class ConflictError(DomainError):
    code = "conflict"
