def has_permission(permissions: list[str], required: str) -> bool:
    """'*' (Owner) always passes; otherwise exact string membership against
    Role.permissions. A pure function so the rule is unit-testable without
    a FastAPI request — api/deps.py's require_permission() is a thin
    wrapper around this."""
    return "*" in permissions or required in permissions
