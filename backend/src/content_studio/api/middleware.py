import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from content_studio.correlation import correlation_scope

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

REQUEST_ID_HEADER = "X-Request-Id"
CORRELATION_ID_HEADER = "X-Correlation-Id"


def get_request_id() -> str | None:
    """Read the current request's id from anywhere in the call stack —
    application services pass this into AuditEvent rows without needing
    the request object threaded through every function signature."""
    return _request_id_var.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assigns (or propagates) a request_id per request, and a
    correlation_id per business operation — the first two links in the
    correlation chain from 16_AUDIT_TRAIL_AND_APPROVALS.md. correlation_id
    defaults to request_id (one request, one operation) but a caller that
    already has a longer-lived operation id (e.g. the web app threading
    one id across create-brief -> approve -> generate) can pass it via
    X-Correlation-Id to link multiple requests under the same trail.
    trace_id/tool_call_id/workflow_id/business_operation_id are threaded
    through by Temporal activities and the MCP tool dispatcher, which run
    outside this per-request scope — see correlation.py."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or request_id
        token = _request_id_var.set(request_id)
        try:
            with correlation_scope(correlation_id=correlation_id):
                response = await call_next(request)
        finally:
            _request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
