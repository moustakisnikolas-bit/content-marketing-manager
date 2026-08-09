import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.mcp.context import AgentContext
from content_studio.mcp.tools import (
    GENERATE_PRODUCT_CAMPAIGN_TOOL,
    GENERATE_PRODUCT_CAMPAIGN_VERSION,
)
from content_studio.modules.commerce.repository import CommerceRepository
from content_studio.modules.commerce.service import CommerceService
from content_studio.modules.governance.tool_governance import ToolGovernanceService
from content_studio.ports.policy import PolicyPort
from content_studio.ports.secrets import SecretsPort
from content_studio.ports.store_connector import StoreConnectorPort

AGENT_NAME = "ecommerce"


async def generate_product_campaign(
    *,
    session: AsyncSession,
    policy: PolicyPort,
    secrets: SecretsPort,
    store_adapter_factory: Callable[[str], StoreConnectorPort],
    context: AgentContext,
    product_id: str,
    goal_slug: str,
    mode: str,
    target_platforms: list[str],
) -> dict[str, Any]:
    """The eCommerce Agent's flagship tool: wraps CommerceService (which
    itself wraps MarketingService) — no business logic lives here, only
    governed exposure. The product's title/description come from a
    synced store, an untrusted source by definition (any store owner, or
    anyone who compromised one, controls that text) — so it's scanned by
    the moderation gate before the tool is allowed to run, per
    15_MCP_AGENTS_AND_SECURITY.md's 'untrusted content never treated as
    instruction' rule."""
    commerce_repo = CommerceRepository(session)
    product = await commerce_repo.get_product_by_id(uuid.UUID(product_id))
    if product is None or product.workspace_id != context.workspace_id:
        return {"authorized": False, "reasons": ["product not found in this workspace"]}

    untrusted_text = f"{product.title}\n{product.description}"
    payload = {
        "product_id": product_id, "goal_slug": goal_slug, "mode": mode,
        "target_platforms": sorted(target_platforms),
    }

    governance = ToolGovernanceService(session, policy=policy)
    authorization = await governance.authorize_tool_call(
        agent_name=AGENT_NAME,
        tool_name=GENERATE_PRODUCT_CAMPAIGN_TOOL,
        tool_version=GENERATE_PRODUCT_CAMPAIGN_VERSION,
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        payload=payload,
        untrusted_text=untrusted_text,
        untrusted_source="product_description",
    )
    if not authorization.allowed:
        return {"authorized": False, "reasons": authorization.reasons}

    commerce_service = CommerceService(session, secrets=secrets, store_adapter_factory=store_adapter_factory)
    proposal = await commerce_service.generate_product_campaign_brief(
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        product_id=uuid.UUID(product_id),
        goal_slug=goal_slug,
        mode=mode,
        target_platforms=target_platforms,
    )
    return {
        "authorized": True,
        "proposal_id": str(proposal.id),
        "objective": proposal.objective,
        "explanation": proposal.explanation,
        "estimated_cost": str(proposal.estimated_cost),
    }
