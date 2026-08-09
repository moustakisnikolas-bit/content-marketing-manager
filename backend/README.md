# Backend

FastAPI modular monolith. See `AI_Content_Studio_Marketing_Manager_Expansion/17_BACKEND_ARCHITECTURE.md` for module boundaries and `29_MONOREPO_STRUCTURE.md` for this directory's internal layout.

Dependency direction: API/MCP -> Application Service -> Repository -> PostgreSQL; Application Service -> Port -> Adapter -> External System; Worker/Temporal Activity -> Application Service.
