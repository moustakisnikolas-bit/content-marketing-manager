class MarketingError(Exception):
    """Base class for marketing-module application errors."""


class GoalNotFound(MarketingError):
    pass


class BriefNotFound(MarketingError):
    pass


class ProposalNotFound(MarketingError):
    pass


class CampaignNotFound(MarketingError):
    pass


class NoActiveRecipe(MarketingError):
    pass
