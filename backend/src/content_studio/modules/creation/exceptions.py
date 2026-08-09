class CreationError(Exception):
    """Base class for creation-module application errors."""


class AssetNotFound(CreationError):
    pass


class AssetTooLarge(CreationError):
    pass
