# AI Content Studio — AI Marketing Manager Expansion

Monorepo root. Full product specification lives in [`AI_Content_Studio_Marketing_Manager_Expansion/`](AI_Content_Studio_Marketing_Manager_Expansion/), starting with `01_PROJECT_OVERVIEW.md` and the authoritative `25_ULTRA_SUPER_MASTER_PROMPT.md`. Technology stack and repo layout decisions are in `28_OSS_TECHNOLOGY_STACK.md` and `29_MONOREPO_STRUCTURE.md`.

## Status

All 8 roadmap phases are built and tested (backend: real Postgres integration tests via testcontainers; frontend: `tsc`/`eslint`), plus post-roadmap production-readiness work (CI/CD, rate limiting, a containerized deploy artifact verified from a clean database) and real Meta (Facebook/Instagram) + WooCommerce integrations for a personal launch. See `infra/docker-compose/README.md` for running the full stack, and `docs/adr/` for architecture decisions made along the way.

## Layout

- `apps/web` — Next.js user and admin panel
- `apps/woocommerce-plugin` — thin WordPress plugin (Phase 6)
- `apps/shopify-app` — Remix + Polaris app (Phase 6)
- `backend` — FastAPI modular monolith
- `infra` — Docker Compose stacks, OPA policies, CI workflows
- `packages` — shared TypeScript types/API contracts
- `docs/adr` — architecture decision records

## Hard Constraints (see `25_ULTRA_SUPER_MASTER_PROMPT.md`)

FastAPI modular monolith, PostgreSQL (sole authoritative store), SQLAlchemy 2.x, Alembic, Redis (broker/coordination only), Temporal, OPA, OpenBao, Langfuse OSS, OpenTelemetry/Prometheus/Grafana. No SQLite, no Oracle, no microservices, no Kubernetes, no Kafka, no GraphQL, no CQRS, no event sourcing without an approved ADR in `docs/adr/`.
