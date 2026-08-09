class PublishingError(Exception):
    """Base class for publishing-module application errors."""


class ConnectionNotFound(PublishingError):
    pass


class CapabilityUnavailable(PublishingError):
    """Raised when a requested publish action isn't backed by a resolved,
    available capability on the connection — 'never pretend a
    direct-publishing capability exists' (10_SOCIAL_PUBLISHING_MODULE.md)."""


class PlanNotFound(PublishingError):
    pass


class InvalidOAuthState(PublishingError):
    pass
