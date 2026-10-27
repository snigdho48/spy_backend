import threading

_thread_locals = threading.local()


def get_audit_context() -> dict:
    return getattr(_thread_locals, "audit_context", {})


def set_audit_context(**kwargs) -> None:
    ctx = getattr(_thread_locals, "audit_context", {})
    ctx.update(kwargs)
    _thread_locals.audit_context = ctx


def clear_audit_context() -> None:
    _thread_locals.audit_context = {}


class AuditContextMiddleware:
    """Capture request metadata for audit logging."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        clear_audit_context()
        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        if not ip:
            ip = request.META.get("REMOTE_ADDR", "")
        set_audit_context(
            ip_address=ip,
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
            request_id=getattr(request, "request_id", ""),
        )
        if hasattr(request, "user") and request.user.is_authenticated:
            set_audit_context(actor_id=str(request.user.id))
        response = self.get_response(request)
        clear_audit_context()
        return response
