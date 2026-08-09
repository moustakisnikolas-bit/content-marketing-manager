# Backend Architecture

## Style

FastAPI modular monolith with API, worker, and scheduler roles.

## Main Modules

- identity, organizations, workspaces, brands
- products, services, stores, connectors
- marketing goals, briefs, campaigns
- planning, creation, assets, reviews
- Audio Studio
- platform connections and publishing
- analytics, attribution, recommendations, experiments
- subscriptions, credits, recipes, costs
- agents, MCP, policy, approvals, audit
- moderation, support, notifications

## Queues

- AI generation
- media processing
- publishing
- analytics ingestion
- store synchronization
- recommendation recomputation
- notifications

## Dependency Direction

```text
API/MCP -> Application Service -> Repository -> PostgreSQL
Application Service -> Internal Port -> Adapter -> External System
Worker/Temporal Activity -> Application Service
```

## Reliability

- idempotency
- retries/backoff
- dead-letter handling
- optimistic concurrency
- cost reservation
- uncertain-outcome reconciliation
- webhook deduplication
- job recovery
