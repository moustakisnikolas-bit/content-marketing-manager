import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.api.deps import (
    WorkspaceContext,
    get_current_user,
    get_db_session,
    get_platform_adapter,
    get_secrets,
    get_workspace_context,
)
from content_studio.modules.analytics.exceptions import InsufficientData, UnknownMetric
from content_studio.modules.analytics.ingestion_service import MetricsIngestionService
from content_studio.modules.analytics.recommendation_engine import RecommendationEngine
from content_studio.modules.analytics.repository import AnalyticsRepository
from content_studio.modules.analytics.schemas import (
    ConversionEventOut,
    ExperimentOut,
    GenerateBestPostingTimeRequest,
    GenerateCampaignComparisonRequest,
    IngestMetricsRequest,
    IngestMetricsResponse,
    MetricDefinitionOut,
    MetricSnapshotOut,
    RecommendationDetailOut,
    RecommendationOut,
    RecommendationOutcomeOut,
    RecordConversionEventRequest,
    RecordRecommendationOutcomeRequest,
)
from content_studio.modules.identity.models import User
from content_studio.modules.publishing.repository import PublishingRepository
from content_studio.ports.secrets import SecretsPort

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/metric-definitions", response_model=list[MetricDefinitionOut])
async def list_metric_definitions(session: AsyncSession = Depends(get_db_session)) -> list[MetricDefinitionOut]:
    repo = AnalyticsRepository(session)
    definitions = await repo.list_metric_definitions()
    return [MetricDefinitionOut.model_validate(d) for d in definitions]


@router.post("/ingest", response_model=IngestMetricsResponse)
async def ingest_metrics(
    body: IngestMetricsRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
    secrets: SecretsPort = Depends(get_secrets),
) -> IngestMetricsResponse:
    publishing_repo = PublishingRepository(session)
    attempt = await publishing_repo.get_attempt_by_id(body.publication_attempt_id)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Publication attempt not found")
    plan = await publishing_repo.get_publication_plan_by_id(attempt.publication_plan_id)
    if plan is None or plan.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Publication attempt not found")

    service = MetricsIngestionService(session, secrets=secrets, platform_adapter_factory=get_platform_adapter)
    snapshots = await service.ingest_for_attempt(body.publication_attempt_id)
    return IngestMetricsResponse(snapshots=[MetricSnapshotOut.model_validate(s) for s in snapshots])


@router.get("/attempts/{attempt_id}/snapshots", response_model=list[MetricSnapshotOut])
async def list_snapshots_for_attempt(
    attempt_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[MetricSnapshotOut]:
    publishing_repo = PublishingRepository(session)
    attempt = await publishing_repo.get_attempt_by_id(attempt_id)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Publication attempt not found")
    plan = await publishing_repo.get_publication_plan_by_id(attempt.publication_plan_id)
    if plan is None or plan.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Publication attempt not found")

    repo = AnalyticsRepository(session)
    snapshots = await repo.list_snapshots_for_attempt(attempt_id)
    return [MetricSnapshotOut.model_validate(s) for s in snapshots]


@router.post("/conversion-events", response_model=ConversionEventOut, status_code=status.HTTP_201_CREATED)
async def record_conversion_event(
    body: RecordConversionEventRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> ConversionEventOut:
    repo = AnalyticsRepository(session)
    event = await repo.create_conversion_event(
        organization_id=context.organization_id,
        workspace_id=context.workspace_id,
        event_type=body.event_type,
        occurred_at=body.occurred_at,
        source=body.source,
        campaign_plan_item_id=body.campaign_plan_item_id,
        value=body.value,
        currency=body.currency,
        consent_confirmed=body.consent_confirmed,
    )
    await session.commit()
    return ConversionEventOut.model_validate(event)


@router.get("/conversion-events", response_model=list[ConversionEventOut])
async def list_conversion_events(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[ConversionEventOut]:
    repo = AnalyticsRepository(session)
    events = await repo.list_conversion_events_for_workspace(context.workspace_id)
    return [ConversionEventOut.model_validate(e) for e in events]


@router.post("/recommendations/best-posting-time", response_model=RecommendationOut, status_code=status.HTTP_201_CREATED)
async def generate_best_posting_time(
    body: GenerateBestPostingTimeRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> RecommendationOut:
    engine = RecommendationEngine(session)
    try:
        recommendation = await engine.generate_best_posting_time(
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            metric_name=body.metric_name,
            data_window_days=body.data_window_days,
        )
    except UnknownMetric as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except InsufficientData as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await session.commit()
    return RecommendationOut.model_validate(recommendation)


@router.get("/recommendations", response_model=list[RecommendationOut])
async def list_recommendations(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[RecommendationOut]:
    repo = AnalyticsRepository(session)
    recommendations = await repo.list_recommendations_for_workspace(context.workspace_id)
    return [RecommendationOut.model_validate(r) for r in recommendations]


@router.get("/recommendations/{recommendation_id}", response_model=RecommendationDetailOut)
async def get_recommendation(
    recommendation_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> RecommendationDetailOut:
    repo = AnalyticsRepository(session)
    recommendation = await repo.get_recommendation_by_id(recommendation_id)
    if recommendation is None or recommendation.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recommendation not found")
    outcomes = await repo.list_outcomes_for_recommendation(recommendation_id)
    return RecommendationDetailOut(
        recommendation=RecommendationOut.model_validate(recommendation),
        outcomes=[RecommendationOutcomeOut.model_validate(o) for o in outcomes],
    )


@router.post(
    "/recommendations/{recommendation_id}/outcomes",
    response_model=RecommendationOutcomeOut,
    status_code=status.HTTP_201_CREATED,
)
async def record_recommendation_outcome(
    recommendation_id: uuid.UUID,
    body: RecordRecommendationOutcomeRequest,
    current_user: User = Depends(get_current_user),
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> RecommendationOutcomeOut:
    repo = AnalyticsRepository(session)
    recommendation = await repo.get_recommendation_by_id(recommendation_id)
    if recommendation is None or recommendation.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recommendation not found")

    outcome = await repo.create_recommendation_outcome(
        recommendation_id=recommendation_id,
        outcome=body.outcome,
        recorded_at=datetime.now(UTC),
        user_id=current_user.id,
        notes=body.notes,
    )
    await session.commit()
    return RecommendationOutcomeOut.model_validate(outcome)


@router.post("/experiments/campaign-comparison", response_model=ExperimentOut, status_code=status.HTTP_201_CREATED)
async def generate_campaign_comparison(
    body: GenerateCampaignComparisonRequest,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> ExperimentOut:
    engine = RecommendationEngine(session)
    try:
        experiment = await engine.generate_campaign_comparison(
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            name=body.name,
            campaign_a_id=body.campaign_a_id,
            campaign_b_id=body.campaign_b_id,
            metric_name=body.metric_name,
        )
    except UnknownMetric as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await session.commit()
    return ExperimentOut.model_validate(experiment)


@router.get("/experiments", response_model=list[ExperimentOut])
async def list_experiments(
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[ExperimentOut]:
    repo = AnalyticsRepository(session)
    experiments = await repo.list_experiments_for_workspace(context.workspace_id)
    return [ExperimentOut.model_validate(e) for e in experiments]


@router.get("/experiments/{experiment_id}", response_model=ExperimentOut)
async def get_experiment(
    experiment_id: uuid.UUID,
    context: WorkspaceContext = Depends(get_workspace_context),
    session: AsyncSession = Depends(get_db_session),
) -> ExperimentOut:
    repo = AnalyticsRepository(session)
    experiment = await repo.get_experiment_by_id(experiment_id)
    if experiment is None or experiment.workspace_id != context.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Experiment not found")
    return ExperimentOut.model_validate(experiment)
