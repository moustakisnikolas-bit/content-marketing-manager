class CommerceError(Exception):
    """Base class for commerce-module application errors."""


class StoreNotFound(CommerceError):
    pass


class ProductNotFound(CommerceError):
    pass


class ConsentRequired(CommerceError):
    """Raised instead of generating abandoned-cart content when consent
    hasn't been explicitly confirmed — never generate on an assumption."""
