from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.mcp.context import AgentContext
from content_studio.mcp.tools import analytics as analytics_tools
from content_studio.mcp.tools import ecommerce as ecommerce_tools
from content_studio.ports.policy import PolicyPort
from content_studio.ports.secrets import SecretsPort
from content_studio.ports.store_connector import StoreConnectorPort


def build_agent_mcp_server(
    *,
    context: AgentContext,
    session: AsyncSession,
    policy: PolicyPort,
    secrets: SecretsPort,
    store_adapter_factory: Callable[[str], StoreConnectorPort],
) -> MCPServer:
    """Builds one real MCP server (github.com/modelcontextprotocol/python-sdk,
    the official open-source SDK) per authenticated session. `context` is
    bound here, in the host process, from the caller's verified JWT and
    workspace membership — never accepted as a tool-call argument an LLM
    could set, per the 'tenant context injected by authenticated host'
    rule. Every registered tool is a thin closure that immediately calls
    ToolGovernanceService before touching any Application Service; see
    mcp/tools/*.py.

    This server is wired for real, in-process MCP protocol tool
    registration/dispatch (verified via server.call_tool() in tests using
    the actual SDK, not a simulation). Exposing it over a network
    transport (stdio/streamable-http) behind an external gateway like
    IBM/mcp-context-forge is a deliberately deferred follow-up — that
    gateway isn't deployed in this dev environment, same category of
    external-infra deferral as Phase 3's social OAuth apps and Phase 6's
    WooCommerce/Shopify apps."""
    server = MCPServer(name="content-studio-agents", version="1.0.0")

    @server.tool(
        name="generate_product_campaign",
        description="Generates a marketing campaign proposal from a synced product's title and description. "
        "High-risk: creates real campaign records and requires an explicit, single-use approval.",
    )
    async def generate_product_campaign(
        product_id: str, goal_slug: str, mode: str, target_platforms: list[str]
    ) -> dict[str, Any]:
        return await ecommerce_tools.generate_product_campaign(
            session=session, policy=policy, secrets=secrets, store_adapter_factory=store_adapter_factory,
            context=context, product_id=product_id, goal_slug=goal_slug, mode=mode,
            target_platforms=target_platforms,
        )

    @server.tool(
        name="generate_best_posting_time",
        description="Generates a best-posting-time recommendation from historical engagement data. "
        "Low-risk, read-only, no approval required.",
    )
    async def generate_best_posting_time(
        metric_name: str = "engagement_rate", data_window_days: int = 90
    ) -> dict[str, Any]:
        return await analytics_tools.generate_best_posting_time(
            session=session, policy=policy, context=context, metric_name=metric_name,
            data_window_days=data_window_days,
        )

    return server
