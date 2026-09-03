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


class PlatformDeleteRejected(PublishingError):
    """The platform itself refused to delete the live post (e.g. a missing
    permission scope, confirmed live for Instagram's instagram_manage_contents)
    — distinct from a plain network/timeout failure, since the fix is
    usually "reconnect the account," not "retry."""

    def __init__(self, platform: str, detail: str) -> None:
        self.platform = platform
        self.detail = detail
        super().__init__(f"{platform} refused to delete the post: {detail}")


class InvalidOAuthState(PublishingError):
    pass
