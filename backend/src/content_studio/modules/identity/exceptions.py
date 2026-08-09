class IdentityError(Exception):
    """Base class for identity-module application errors."""


class EmailAlreadyRegistered(IdentityError):
    pass


class InvalidCredentials(IdentityError):
    pass


class InvalidRefreshToken(IdentityError):
    pass


class UserNotFound(IdentityError):
    pass


class RoleNotFound(IdentityError):
    pass


class WorkspaceNotFound(IdentityError):
    pass


class InvitationNotFound(IdentityError):
    pass


class InvitationNotPending(IdentityError):
    pass


class ApiKeyNotFound(IdentityError):
    pass


class BrandProfileNotFound(IdentityError):
    pass


class BrandRuleNotFound(IdentityError):
    pass
