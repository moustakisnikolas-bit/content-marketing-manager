from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.mcp.context import AgentContext
from content_studio.mcp.tools import (
    GENERATE_BEST_POSTING_TIME_TOOL,
    GENERATE_BEST_POSTING_TIME_VERSION,
)
from content_studio.modules.analytics.exceptions import InsufficientData, UnknownMetric
from content_studio.modules.analytics.recommendation_engine import RecommendationEngine
from content_studio.modules.governance.tool_governance import ToolGovernanceService
from content_studio.ports.policy import PolicyPort

AGENT_NAME = "analytics_recommendation"


async def generate_best_posting_time(
    *,
    session: AsyncSession,
    policy: PolicyPort,
    context: AgentContext,
    metric_name: str = "engagement_rate",
    data_window_days: int = 90,
) -> dict[str, Any]:
    """The Analytics/Recommendation Agent's tool: wraps RecommendationEngine
    directly — read-only, no cost, no side effects, so it's registered
    low-risk and auto-allowed by OPA without a human approval step,
    contrasting with the ecommerce agent's high-risk tool above. Every
    number in the result already carries its own confidence/sample-size
    honesty (see recommendation_engine.py) — the tool wrapper adds
    governance, not a second layer of claims."""
    governance = ToolGovernanceService(session, policy=policy)
    payload = {"metric_name": metric_name, "data_window_days": data_window_days}
    authorization = await governance.authorize_tool_call(
        agent_name=AGENT_NAME,
        tool_name=GENERATE_BEST_POSTING_TIME_TOOL,
        tool_version=GENERATE_BEST_POSTING_TIME_VERSION,
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        payload=payload,
    )
    if not authorization.allowed:
        return {"authorized": False, "reasons": authorization.reasons}

    engine = RecommendationEngine(session)
    try:
        recommendation = await engine.generate_best_posting_time(
            organization_id=context.organization_id, workspace_id=context.workspace_id,
            metric_name=metric_name, data_window_days=data_window_days,
        )
    except (InsufficientData, UnknownMetric) as exc:
        return {"authorized": True, "generated": False, "reason": str(exc)}

    return {
        "authorized": True,
        "generated": True,
        "recommendation_id": str(recommendation.id),
        "confidence": recommendation.confidence,
        "explanation": recommendation.explanation,
    }
