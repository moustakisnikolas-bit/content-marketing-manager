class GovernanceError(Exception):
    """Base class for governance-module application errors."""


class AgentNotFound(GovernanceError):
    pass


class ToolNotFound(GovernanceError):
    pass


class ApprovalNotFound(GovernanceError):
    pass
