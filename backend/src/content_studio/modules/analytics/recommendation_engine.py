import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from content_studio.modules.analytics.exceptions import InsufficientData, UnknownMetric
from content_studio.modules.analytics.models import Experiment, Recommendation
from content_studio.modules.analytics.repository import AnalyticsRepository
from content_studio.modules.marketing.repository import MarketingRepository

DEFAULT_STRATEGY_VERSION_NAME = "deterministic_v1"

# Sample-size-aware confidence, per 09_RECOMMENDATION_ENGINE.md's rule that
# a recommendation must honestly state low confidence rather than invent
# certainty. Thresholds are deliberately simple and documented, not tuned
# statistics — this is a floor for "enough data to say anything at all",
# not a claim of statistical significance.
_LOW_CONFIDENCE_MAX = 4
_MEDIUM_CONFIDENCE_MAX = 19

# Two campaigns need at least this many samples each before a winner is
# ever declared — below this, the honest answer is "not enough data yet",
# never a guess dressed up as a result.
MIN_SAMPLES_PER_CAMPAIGN = 3
# Means closer than this (as a fraction of the larger mean) are treated as
# "too close to call" rather than manufacturing a winner from noise.
INCONCLUSIVE_MARGIN = Decimal("0.05")

_DAYPARTS: list[tuple[str, range]] = [
    ("night", range(5)),
    ("morning", range(5, 12)),
    ("afternoon", range(12, 17)),
    ("evening", range(17, 24)),
]

# Anchor clock hour used to turn a winning daypart into an actual
# scheduled_for datetime — the midpoint of each bucket's range.
_DAYPART_ANCHOR_HOUR = {"night": 3, "morning": 9, "afternoon": 14, "evening": 19}

# Fixed, honest fallback ordering for (weekday, daypart) buckets with no
# real history yet — weekday evenings first (typically the highest social
# engagement window), then weekday afternoons, weekend evenings/afternoons,
# weekday mornings, and finally every night bucket last. Never claims to
# be data-driven; rank_weekly_slots() only reaches into this for buckets
# real history hasn't covered, so it always has a full week of slots to
# offer without ever dressing up a guess as a result. weekday follows
# Python's datetime.weekday(): Monday=0 .. Sunday=6. Covers all 7*4=28
# (weekday, daypart) combinations exactly once.
_FALLBACK_WEEKLY_ORDER: list[tuple[int, str]] = [
    (0, "evening"), (1, "evening"), (2, "evening"), (3, "evening"), (4, "evening"),
    (5, "morning"), (6, "morning"),
    (0, "afternoon"), (1, "afternoon"), (2, "afternoon"), (3, "afternoon"), (4, "afternoon"),
    (5, "evening"), (6, "evening"),
    (5, "afternoon"), (6, "afternoon"),
    (0, "morning"), (1, "morning"), (2, "morning"), (3, "morning"), (4, "morning"),
    (0, "night"), (1, "night"), (2, "night"), (3, "night"), (4, "night"), (5, "night"), (6, "night"),
]


def _next_occurrence(now: datetime, *, weekday: int, hour: int, weeks_out: int = 0) -> datetime:
    """The next real datetime landing on `weekday` (Monday=0..Sunday=6) at
    `hour`, pushed out by an additional `weeks_out` full weeks."""
    days_ahead = (weekday - now.weekday()) % 7
    candidate = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate + timedelta(weeks=weeks_out)


def confidence_for_sample_size(n: int) -> str:
    if n <= _LOW_CONFIDENCE_MAX:
        return "low"
    if n <= _MEDIUM_CONFIDENCE_MAX:
        return "medium"
    return "high"


def _daypart_for_hour(hour: int) -> str:
    for name, hours in _DAYPARTS:
        if hour in hours:
            return name
    raise AssertionError(f"unreachable: hour {hour} not in any daypart")


@dataclass(frozen=True)
class _BucketStats:
    avg: Decimal
    sample_size: int


class RecommendationEngine:
    """Deterministic, statistical-only. No ML/LLM anywhere in this class —
    per the spec's explicit gating rule, predictive models stay dormant
    (ModelVersion) until versioned training data, offline evaluation, and
    drift monitoring exist. Every claim here is a plain aggregate over
    real MetricSnapshot rows, phrased correlationally."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = AnalyticsRepository(session)
        self._marketing_repo = MarketingRepository(session)

    async def _active_strategy_version_id(self) -> uuid.UUID:
        version = await self._repo.get_active_strategy_version()
        assert version is not None, "no active StrategyVersion — run db/seed.py's ensure_default_strategy_version"
        return version.id

    async def generate_best_posting_time(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        metric_name: str = "engagement_rate",
        data_window_days: int = 90,
    ) -> Recommendation:
        definition = await self._repo.get_metric_definition_by_name(metric_name)
        if definition is None:
            raise UnknownMetric(metric_name)

        since = datetime.now(UTC) - timedelta(days=data_window_days)
        snapshots = await self._repo.list_snapshots_for_workspace_metric(
            workspace_id=workspace_id, metric_definition_id=definition.id, since=since
        )
        if not snapshots:
            raise InsufficientData(
                f"No {metric_name} data in the last {data_window_days} days yet - publish and ingest metrics "
                "for at least one post before requesting a posting-time recommendation."
            )

        buckets: dict[str, list[Decimal]] = {name: [] for name, _ in _DAYPARTS}
        for snapshot in snapshots:
            daypart = _daypart_for_hour(snapshot.measurement_time.hour)
            buckets[daypart].append(snapshot.normalized_value)

        bucket_stats = {
            name: _BucketStats(avg=sum(values, Decimal(0)) / len(values), sample_size=len(values))
            for name, values in buckets.items()
            if values
        }
        best_bucket = max(bucket_stats, key=lambda name: bucket_stats[name].avg)
        sample_size = len(snapshots)
        confidence = confidence_for_sample_size(sample_size)

        explanation = (
            f"Posts measured during the {best_bucket} window show the highest average {metric_name} "
            f"({bucket_stats[best_bucket].avg:.4f}) across {bucket_stats[best_bucket].sample_size} "
            f"of {sample_size} total samples from the last {data_window_days} days. This is an association "
            "in your own historical data, not a guarantee - it does not claim posting time causes the "
            "difference in engagement."
        )
        if confidence == "low":
            explanation += (
                f" Confidence is low: only {sample_size} data points exist so far. Treat this as an early "
                "hypothesis to test, not a settled conclusion."
            )

        now = datetime.now(UTC)
        return await self._repo.create_recommendation(
            organization_id=organization_id,
            workspace_id=workspace_id,
            strategy_version_id=await self._active_strategy_version_id(),
            recommendation_type="best_posting_time",
            objective=f"Increase {metric_name} by publishing during your best-performing time of day",
            score=bucket_stats[best_bucket].avg,
            confidence=confidence,
            evidence={
                "metric": metric_name,
                "best_bucket": best_bucket,
                "buckets": {
                    name: {"avg": str(stats.avg), "sample_size": stats.sample_size}
                    for name, stats in bucket_stats.items()
                },
            },
            sample_size=sample_size,
            data_window_days=data_window_days,
            explanation=explanation,
            expires_at=now + timedelta(days=30),
            created_at=now,
        )

    async def rank_weekly_slots(
        self, *, workspace_id: uuid.UUID, metric_name: str = "engagement_rate",
    ) -> list[tuple[int, int]]:
        """Every (weekday, anchor_hour) combination ranked best-to-worst —
        real-data buckets first (descending average `metric_name`, from
        this workspace's own ingested Meta post history), then
        `_FALLBACK_WEEKLY_ORDER` fills in any bucket with no samples yet.
        weekday follows Python's datetime.weekday(): Monday=0..Sunday=6.
        Always returns all 28 combinations — real data never runs out of
        slots to fall back to, and a bucket with real samples always
        outranks one without, however few samples it has."""
        definition = await self._repo.get_metric_definition_by_name(metric_name)
        snapshots = (
            await self._repo.list_snapshots_for_workspace_metric(
                workspace_id=workspace_id, metric_definition_id=definition.id
            )
            if definition is not None
            else []
        )

        buckets: dict[tuple[int, str], list[Decimal]] = {}
        for snapshot in snapshots:
            key = (snapshot.measurement_time.weekday(), _daypart_for_hour(snapshot.measurement_time.hour))
            buckets.setdefault(key, []).append(snapshot.normalized_value)

        real_ranked = sorted(
            buckets, key=lambda key: sum(buckets[key], Decimal(0)) / len(buckets[key]), reverse=True
        )
        fallback_remaining = [key for key in _FALLBACK_WEEKLY_ORDER if key not in buckets]
        return [(weekday, _DAYPART_ANCHOR_HOUR[daypart]) for weekday, daypart in real_ranked + fallback_remaining]

    async def suggest_weekly_schedule(
        self, *, workspace_id: uuid.UUID, count: int, items_per_week: int, metric_name: str = "engagement_rate",
    ) -> list[datetime]:
        """The next `count` future publish times, `items_per_week` of them
        per calendar week, each week's slots taken from the top of
        rank_weekly_slots() in order — the single best slot goes to the
        first item scheduled in a given week, and once that week's quota
        is filled the next item rolls into the following week at the
        top slot again, instead of dumping an arbitrary number of items
        into the next few days regardless of how many there are."""
        if count <= 0:
            return []
        items_per_week = max(items_per_week, 1)
        ranked = await self.rank_weekly_slots(workspace_id=workspace_id, metric_name=metric_name)
        now = datetime.now(UTC)
        schedule: list[datetime] = []
        for i in range(count):
            week_offset = i // items_per_week
            weekday, hour = ranked[(i % items_per_week) % len(ranked)]
            schedule.append(_next_occurrence(now, weekday=weekday, hour=hour, weeks_out=week_offset))
        return schedule

    async def generate_campaign_comparison(
        self,
        *,
        organization_id: uuid.UUID,
        workspace_id: uuid.UUID,
        name: str,
        campaign_a_id: uuid.UUID,
        campaign_b_id: uuid.UUID,
        metric_name: str = "engagement_rate",
    ) -> Experiment:
        definition = await self._repo.get_metric_definition_by_name(metric_name)
        if definition is None:
            raise UnknownMetric(metric_name)

        items_a = await self._marketing_repo.list_plan_items_for_campaign(campaign_a_id)
        items_b = await self._marketing_repo.list_plan_items_for_campaign(campaign_b_id)
        snapshots_a = await self._repo.list_snapshots_for_plan_items_metric(
            plan_item_ids=[i.id for i in items_a], metric_definition_id=definition.id
        )
        snapshots_b = await self._repo.list_snapshots_for_plan_items_metric(
            plan_item_ids=[i.id for i in items_b], metric_definition_id=definition.id
        )
        n_a, n_b = len(snapshots_a), len(snapshots_b)
        mean_a = sum((s.normalized_value for s in snapshots_a), Decimal(0)) / n_a if n_a else None
        mean_b = sum((s.normalized_value for s in snapshots_b), Decimal(0)) / n_b if n_b else None

        evidence = {
            "metric": metric_name,
            "campaign_a": {"mean": str(mean_a) if mean_a is not None else None, "sample_size": n_a},
            "campaign_b": {"mean": str(mean_b) if mean_b is not None else None, "sample_size": n_b},
        }

        if n_a < MIN_SAMPLES_PER_CAMPAIGN or n_b < MIN_SAMPLES_PER_CAMPAIGN:
            winner = "inconclusive"
            result_summary = (
                f"Not enough data yet: campaign A has {n_a} sample(s) and campaign B has {n_b}, but at least "
                f"{MIN_SAMPLES_PER_CAMPAIGN} each are needed before comparing {metric_name}."
            )
        else:
            # n_a/n_b >= MIN_SAMPLES_PER_CAMPAIGN (> 0) here, so mean_a/mean_b
            # were computed, not left None — mypy can't see that correlation
            # across the two independent ternaries above, so spell it out.
            assert mean_a is not None and mean_b is not None
            larger = max(mean_a, mean_b)
            relative_diff = abs(mean_a - mean_b) / larger if larger else Decimal(0)
            if relative_diff < INCONCLUSIVE_MARGIN:
                winner = "inconclusive"
                result_summary = (
                    f"Campaign A averaged {mean_a:.4f} {metric_name} ({n_a} samples) and campaign B averaged "
                    f"{mean_b:.4f} ({n_b} samples) - too close to call a winner from this data alone."
                )
            else:
                winner = "a" if mean_a > mean_b else "b"
                winning_mean, other_mean = (mean_a, mean_b) if winner == "a" else (mean_b, mean_a)
                result_summary = (
                    f"Campaign {winner.upper()} shows a higher average {metric_name} ({winning_mean:.4f} vs "
                    f"{other_mean:.4f}) across {n_a} and {n_b} samples respectively. This reflects an "
                    "association observed in your data, not a controlled causal test."
                )

        now = datetime.now(UTC)
        return await self._repo.create_experiment(
            organization_id=organization_id,
            workspace_id=workspace_id,
            name=name,
            campaign_a_id=campaign_a_id,
            campaign_b_id=campaign_b_id,
            metric_definition_id=definition.id,
            winner=winner,
            evidence=evidence,
            result_summary=result_summary,
            created_at=now,
        )
