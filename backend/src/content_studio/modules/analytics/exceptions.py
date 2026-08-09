class AnalyticsError(Exception):
    """Base class for analytics-module application errors."""


class UnknownMetric(AnalyticsError):
    def __init__(self, metric_name: str) -> None:
        super().__init__(f"Unknown metric definition: {metric_name!r}")
        self.metric_name = metric_name


class InsufficientData(AnalyticsError):
    """Raised instead of returning a fabricated recommendation when there
    isn't enough real data to say anything honest — never silently invent
    a low-confidence answer from zero samples."""
