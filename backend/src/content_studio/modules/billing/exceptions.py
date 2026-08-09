class BillingError(Exception):
    """Base class for billing-module application errors."""


class InsufficientCredits(BillingError):
    pass


class ReservationNotFound(BillingError):
    pass


class ReservationNotReserved(BillingError):
    """Raised when settle/release is attempted on a reservation that has
    already been settled or released — reservations are single-use."""


class SubscriptionNotFound(BillingError):
    pass
