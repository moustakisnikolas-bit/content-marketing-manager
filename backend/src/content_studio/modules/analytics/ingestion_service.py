import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.analytics.models import MetricSnapshot
from content_studio.modules.analytics.repository import AnalyticsRepository
from content_studio.modules.marketing.repository import MarketingRepository
from content_studio.modules.publishing.repository import PublishingRepository
from content_studio.ports.secrets import SecretsPort
from content_studio.ports.social_platform import SocialPlatformPort

# Maps a provider's raw field name onto our normalized metric catalog.
# Deliberately hand-maintained per provider shape (see get_post_metrics'
# docstring) rather than inferred, since providers use inconsistent field
# names for the same concept (e.g. "views" on YouTube vs "impressions"
# elsewhere) and silently guessing would violate the "never fabricate
# evidence" rule this whole module is built around.
_RAW_FIELD_TO_METRIC: dict[str, str] = {
    "impressions": "impressions",
    "views": "impressions",
    "likes": "likes",
    "comments": "comments",
    "shares": "shares",
    "link_clicks": "link_clicks",
    "averageViewDurationSeconds": "avg_view_duration_seconds",
}

_ENGAGEMENT_FIELDS = ("likes", "comments", "shares")


class MetricsIngestionService:
    """Pulls a post's current metrics from its platform, and writes them
    into the append-only MetricSnapshot ledger with the dual raw+normalized
    storage the analytics module is built around. One call = one new set of
    snapshots (a fresh point-in-time read), never an update to a prior one."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        secrets: SecretsPort,
        platform_adapter_factory: Callable[[str], SocialPlatformPort],
    ) -> None:
        self._session = session
        self._repo = AnalyticsRepository(session)
        self._publishing_repo = PublishingRepository(session)
        self._marketing_repo = MarketingRepository(session)
        self._secrets = secrets
        self._platform_adapter_factory = platform_adapter_factory

    async def ingest_for_attempt(self, attempt_id: uuid.UUID) -> list[MetricSnapshot]:
        attempt = await self._publishing_repo.get_attempt_by_id(attempt_id)
        if attempt is None or attempt.external_post_id is None:
            return []

        plan = await self._publishing_repo.get_publication_plan_by_id(attempt.publication_plan_id)
        assert plan is not None
        connection = await self._publishing_repo.get_connection_by_id(plan.platform_connection_id)
        assert connection is not None

        access_token = await self._secrets.unseal(reference=connection.access_token_secret_ref)
        adapter = self._platform_adapter_factory(connection.platform)
        raw_payload = await adapter.get_post_metrics(access_token=access_token, external_post_id=attempt.external_post_id)

        plan_item = await self._marketing_repo.get_plan_item_by_publication_plan_id(plan.id)
        now = datetime.now(UTC)

        engagement_total = sum(
            (Decimal(str(raw_payload[f])) for f in _ENGAGEMENT_FIELDS if f in raw_payload), Decimal(0)
        )
        reach = raw_payload.get("impressions") or raw_payload.get("views")

        computed: dict[str, Decimal] = {}
        for raw_field, value in raw_payload.items():
            metric_name = _RAW_FIELD_TO_METRIC.get(raw_field)
            if metric_name is None or not isinstance(value, (int, float)):
                continue
            computed[metric_name] = Decimal(str(value))
        if any(f in raw_payload for f in _ENGAGEMENT_FIELDS):
            computed["engagement_total"] = engagement_total
            if reach:
                computed["engagement_rate"] = (engagement_total / Decimal(str(reach))).quantize(Decimal("0.000001"))

        snapshots: list[MetricSnapshot] = []
        for metric_name, normalized_value in computed.items():
            definition = await self._repo.get_metric_definition_by_name(metric_name)
            if definition is None:
                continue
            snapshot = await self._repo.create_metric_snapshot(
                organization_id=plan.organization_id,
                workspace_id=plan.workspace_id,
                metric_definition_id=definition.id,
                raw_provider_name=connection.platform,
                raw_payload=raw_payload,
                normalized_value=normalized_value,
                measurement_time=now,
                collection_time=now,
                publication_attempt_id=attempt.id,
                campaign_plan_item_id=plan_item.id if plan_item else None,
            )
            snapshots.append(snapshot)

        await self._session.commit()
        return snapshots
