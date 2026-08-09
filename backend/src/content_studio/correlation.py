"""The correlation chain from 16_AUDIT_TRAIL_AND_APPROVALS.md:
request_id, correlation_id, trace_id, tool_call_id, workflow_id,
business_operation_id — threaded across gateway, OPA, Temporal, workers,
and PostgreSQL so one business action can be traced end-to-end.

request_id (api/middleware.py) is per-HTTP-request and already wired since
Phase 1. The remaining ids live here, framework-agnostic, since Temporal
activities and the MCP tool dispatcher run outside any Starlette request
context and contextvars don't cross process boundaries — an activity must
explicitly re-enter a correlation_scope with the value it received as
workflow/activity input, not inherit one from the API process.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from opentelemetry import trace

_correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_tool_call_id_var: ContextVar[str | None] = ContextVar("tool_call_id", default=None)
_workflow_id_var: ContextVar[str | None] = ContextVar("workflow_id", default=None)
_business_operation_id_var: ContextVar[str | None] = ContextVar("business_operation_id", default=None)


def get_correlation_id() -> str | None:
    return _correlation_id_var.get()


def get_trace_id() -> str | None:
    """Reads the active OpenTelemetry span's trace id rather than minting
    a second, redundant identifier — OTel is already live on every request
    (see observability.py), so the Postgres audit trail and Grafana/OTel
    tracing share the same id instead of two unrelated ones."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return format(span_context.trace_id, "032x")


def get_tool_call_id() -> str | None:
    return _tool_call_id_var.get()


def get_workflow_id() -> str | None:
    return _workflow_id_var.get()


def get_business_operation_id() -> str | None:
    return _business_operation_id_var.get()


@contextmanager
def correlation_scope(
    *,
    correlation_id: str | None = None,
    tool_call_id: str | None = None,
    workflow_id: str | None = None,
    business_operation_id: str | None = None,
) -> Iterator[None]:
    """Sets whichever ids are given for the duration of the block. Used by:
    RequestIDMiddleware (correlation_id, per HTTP request), Temporal
    activities (workflow_id, from activity.info()), and the MCP tool
    dispatcher (tool_call_id + business_operation_id, per tool
    invocation)."""
    resets = []
    for var, value in (
        (_correlation_id_var, correlation_id),
        (_tool_call_id_var, tool_call_id),
        (_workflow_id_var, workflow_id),
        (_business_operation_id_var, business_operation_id),
    ):
        if value is not None:
            resets.append((var, var.set(value)))
    try:
        yield
    finally:
        for var, token in reversed(resets):
            var.reset(token)
