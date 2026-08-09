import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.analytics.models import (
    ConversionEvent,
    Experiment,
    MetricDefinition,
    MetricSnapshot,
    Recommendation,
    RecommendationOutcome,
    StrategyVersion,
)


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- Metric definitions ------------------------------------------------

    async def get_metric_definition_by_name(self, name: str) -> MetricDefinition | None:
        result = await self._session.execute(select(MetricDefinition).where(MetricDefinition.name == name))
        return result.scalar_one_or_none()

    async def get_metric_definition_by_id(self, definition_id: uuid.UUID) -> MetricDefinition | None:
        return await self._session.get(MetricDefinition, definition_id)

    async def create_metric_definition(self, *, name: str, unit: str, scope: str, description: str) -> MetricDefinition:
        definition = MetricDefinition(name=name, unit=unit, scope=scope, description=description)
        self._session.add(definition)
        await self._session.flush()
        return definition

    async def list_metric_definitions(self) -> list[MetricDefinition]:
        result = await self._session.execute(select(MetricDefinition).order_by(MetricDefinition.name))
        return list(result.scalars().all())

    # -- Metric snapshots ---------------------------------------------------

    async def create_metric_snapshot(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        metric_definition_id: uuid.UUID,
        raw_provider_name: str,
        raw_payload: dict,
        normalized_value: Decimal,
        measurement_time: datetime,
        collection_time: datetime,
        publication_attempt_id: uuid.UUID | None = None,
        campaign_plan_item_id: uuid.UUID | None = None,
        attribution_window_days: int | None = None,
        currency: str | None = None,
    ) -> MetricSnapshot:
        snapshot = MetricSnapshot(
            organization_id=organization_id,
            workspace_id=workspace_id,
            metric_definition_id=metric_definition_id,
            publication_attempt_id=publication_attempt_id,
            campaign_plan_item_id=campaign_plan_item_id,
            raw_provider_name=raw_provider_name,
            raw_payload=raw_payload,
            normalized_value=normalized_value,
            measurement_time=measurement_time,
            collection_time=collection_time,
            attribution_window_days=attribution_window_days,
            currency=currency,
        )
        self._session.add(snapshot)
        await self._session.flush()
        return snapshot

    async def list_snapshots_for_attempt(self, publication_attempt_id: uuid.UUID) -> list[MetricSnapshot]:
        result = await self._session.execute(
            select(MetricSnapshot)
            .where(MetricSnapshot.publication_attempt_id == publication_attempt_id)
            .order_by(MetricSnapshot.collection_time.desc())
        )
        return list(result.scalars().all())

    async def list_snapshots_for_workspace_metric(
        self, *, workspace_id: uuid.UUID, metric_definition_id: uuid.UUID, since: datetime | None = None
    ) -> list[MetricSnapshot]:
        stmt = select(MetricSnapshot).where(
            MetricSnapshot.workspace_id == workspace_id,
            MetricSnapshot.metric_definition_id == metric_definition_id,
        )
        if since is not None:
            stmt = stmt.where(MetricSnapshot.measurement_time >= since)
        stmt = stmt.order_by(MetricSnapshot.measurement_time)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_snapshots_for_plan_items_metric(
        self, *, plan_item_ids: list[uuid.UUID], metric_definition_id: uuid.UUID, since: datetime | None = None
    ) -> list[MetricSnapshot]:
        if not plan_item_ids:
            return []
        stmt = select(MetricSnapshot).where(
            MetricSnapshot.campaign_plan_item_id.in_(plan_item_ids),
            MetricSnapshot.metric_definition_id == metric_definition_id,
        )
        if since is not None:
            stmt = stmt.where(MetricSnapshot.measurement_time >= since)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # -- Conversion events ---------------------------------------------------

    async def create_conversion_event(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        event_type: str,
        occurred_at: datetime,
        source: str,
        campaign_plan_item_id: uuid.UUID | None = None,
        value: Decimal | None = None,
        currency: str | None = None,
        consent_confirmed: bool = False,
    ) -> ConversionEvent:
        event = ConversionEvent(
            organization_id=organization_id,
            workspace_id=workspace_id,
            campaign_plan_item_id=campaign_plan_item_id,
            event_type=event_type,
            value=value,
            currency=currency,
            occurred_at=occurred_at,
            consent_confirmed=consent_confirmed,
            source=source,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_conversion_events_for_workspace(self, workspace_id: uuid.UUID) -> list[ConversionEvent]:
        result = await self._session.execute(
            select(ConversionEvent)
            .where(ConversionEvent.workspace_id == workspace_id)
            .order_by(ConversionEvent.occurred_at.desc())
        )
        return list(result.scalars().all())

    # -- Strategy versions ---------------------------------------------------

    async def get_active_strategy_version(self) -> StrategyVersion | None:
        result = await self._session.execute(
            select(StrategyVersion)
            .where(StrategyVersion.is_active.is_(True))
            .order_by(StrategyVersion.created_at.desc())
        )
        return result.scalars().first()

    async def get_strategy_version_by_name(self, name: str) -> StrategyVersion | None:
        result = await self._session.execute(select(StrategyVersion).where(StrategyVersion.name == name))
        return result.scalar_one_or_none()

    async def create_strategy_version(self, *, name: str, description: str, is_active: bool = True) -> StrategyVersion:
        version = StrategyVersion(name=name, description=description, is_active=is_active)
        self._session.add(version)
        await self._session.flush()
        return version

    # -- Recommendations ---------------------------------------------------

    async def create_recommendation(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        strategy_version_id: uuid.UUID,
        recommendation_type: str,
        objective: str,
        score: Decimal,
        confidence: str,
        evidence: dict,
        sample_size: int,
        data_window_days: int,
        explanation: str,
        expires_at: datetime,
        created_at: datetime,
    ) -> Recommendation:
        recommendation = Recommendation(
            organization_id=organization_id,
            workspace_id=workspace_id,
            strategy_version_id=strategy_version_id,
            recommendation_type=recommendation_type,
            objective=objective,
            score=score,
            confidence=confidence,
            evidence=evidence,
            sample_size=sample_size,
            data_window_days=data_window_days,
            explanation=explanation,
            expires_at=expires_at,
            created_at=created_at,
        )
        self._session.add(recommendation)
        await self._session.flush()
        return recommendation

    async def get_recommendation_by_id(self, recommendation_id: uuid.UUID) -> Recommendation | None:
        return await self._session.get(Recommendation, recommendation_id)

    async def list_recommendations_for_workspace(self, workspace_id: uuid.UUID) -> list[Recommendation]:
        result = await self._session.execute(
            select(Recommendation)
            .where(Recommendation.workspace_id == workspace_id)
            .order_by(Recommendation.created_at.desc())
        )
        return list(result.scalars().all())

    # -- Recommendation outcomes ---------------------------------------------

    async def create_recommendation_outcome(
        self,
        *,
        recommendation_id: uuid.UUID,
        outcome: str,
        recorded_at: datetime,
        user_id: uuid.UUID | None = None,
        notes: str | None = None,
    ) -> RecommendationOutcome:
        row = RecommendationOutcome(
            recommendation_id=recommendation_id,
            outcome=outcome,
            user_id=user_id,
            notes=notes,
            recorded_at=recorded_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_outcomes_for_recommendation(self, recommendation_id: uuid.UUID) -> list[RecommendationOutcome]:
        result = await self._session.execute(
            select(RecommendationOutcome)
            .where(RecommendationOutcome.recommendation_id == recommendation_id)
            .order_by(RecommendationOutcome.recorded_at)
        )
        return list(result.scalars().all())

    # -- Experiments ---------------------------------------------------------

    async def create_experiment(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        name: str,
        campaign_a_id: uuid.UUID,
        campaign_b_id: uuid.UUID,
        metric_definition_id: uuid.UUID,
        winner: str,
        evidence: dict,
        result_summary: str,
        created_at: datetime,
    ) -> Experiment:
        experiment = Experiment(
            organization_id=organization_id,
            workspace_id=workspace_id,
            name=name,
            campaign_a_id=campaign_a_id,
            campaign_b_id=campaign_b_id,
            metric_definition_id=metric_definition_id,
            winner=winner,
            evidence=evidence,
            result_summary=result_summary,
            created_at=created_at,
        )
        self._session.add(experiment)
        await self._session.flush()
        return experiment

    async def get_experiment_by_id(self, experiment_id: uuid.UUID) -> Experiment | None:
        return await self._session.get(Experiment, experiment_id)

    async def list_experiments_for_workspace(self, workspace_id: uuid.UUID) -> list[Experiment]:
        result = await self._session.execute(
            select(Experiment).where(Experiment.workspace_id == workspace_id).order_by(Experiment.created_at.desc())
        )
        return list(result.scalars().all())
