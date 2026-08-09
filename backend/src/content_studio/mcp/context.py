import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentContext:
    """Tenant/identity context injected by the authenticated host — the
    FastAPI process that owns the caller's verified session — never
    supplied by the LLM or the tool-call arguments themselves. Per
    15_MCP_AGENTS_AND_SECURITY.md: 'tenant context injected by
    authenticated host'. Tool functions receive this out-of-band as a
    Python parameter the server binds per-session, not as a field an LLM
    could set in its tool-call JSON."""

    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
