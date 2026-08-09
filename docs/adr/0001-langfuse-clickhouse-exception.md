# ADR-0001: Langfuse OSS Self-Hosting Requires ClickHouse, Redis, and S3

## Status
Proposed

## Context
The core spec mandates Langfuse OSS for LLM/agent observability and separately states PostgreSQL as the sole authoritative store, with no other database named as permitted. Langfuse's self-hosted deployment (v3/v4) is a multi-container stack: web, worker, Postgres (metadata), ClickHouse (trace/observation storage), Redis (queue), and S3-compatible blob storage. This is inherent to how the mandated tool is built, not a choice this project is making.

## Decision
Adopt Langfuse's full stack as shipped, including ClickHouse. Scope ClickHouse strictly to Langfuse's internal trace/observation storage:
- No application code queries ClickHouse directly.
- No business entity from the core schema (`18_DATABASE_SCHEMA_POSTGRESQL.md`) is ever authoritative in ClickHouse — `AuditEvent`, `CampaignDecision`, and all other business records stay in PostgreSQL.
- Langfuse's S3 requirement points at the same SeaweedFS instance used elsewhere, for operational consistency, not a second storage system.
- Langfuse's own Redis queue is understood as scoped to Langfuse's internals, distinct from the application's Redis (broker/coordination only, never source of truth).

## Consequences
- One additional stateful service (ClickHouse) to operate and back up, outside the "PostgreSQL only" rule, justified as tool-scoped rather than architectural.
- If Langfuse is ever replaced, this exception is removed with it — no application code should ever come to depend on ClickHouse being present.
