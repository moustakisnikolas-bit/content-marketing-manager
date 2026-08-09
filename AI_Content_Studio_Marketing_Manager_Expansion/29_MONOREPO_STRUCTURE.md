# Monorepo Structure

## Status

Companion to `28_OSS_TECHNOLOGY_STACK.md`. Describes the top-level repository layout for implementation. The physical scaffold (empty directories with placeholder READMEs) lives at the repository root, one level above this documentation pack.

## Top Level

- `apps/web` — Next.js user and admin panel (shadcn/ui, Tremor, TanStack Query, FullCalendar)
- `apps/woocommerce-plugin` — thin PHP plugin, no AI logic, no provider keys
- `apps/shopify-app` — Remix + Polaris app
- `backend` — FastAPI modular monolith
- `infra` — Docker Compose stacks, OPA policy source, CI workflow definitions
- `packages` — shared TypeScript types and generated API contracts, consumed by `web` and `shopify-app`
- `docs/adr` — architecture decision records

## Backend Internal Structure

```
backend/src/
├── api/           /api/v1 routers and request/response schemas
├── mcp/           MCP tool wrappers exposed via the MCP Gateway
├── modules/
│   ├── identity/      User, Organization, Workspace, Membership, Role, BrandProfile, BrandRule
│   ├── commerce/      StoreConnection, StoreCapability, StoreSyncCursor, Product, ProductVariant, ProductAsset, ProductPerformanceSnapshot, StoreWebhookDelivery
│   ├── marketing/     MarketingGoal, MarketingBrief, CampaignProposal, Campaign, CampaignPlanItem, CampaignVariant, CampaignDecision, CampaignOutcome, AutoPilotPolicy
│   ├── creation/      ContentItem, ContentRevision, ContentPackage, Review, Asset, AssetRelationship, GenerationJob, GenerationAttempt
│   ├── audio/         AudioAlbum, AudioTrack, AudioComposition, AudioLayer, FrequencySegment, MusicRelease, TrackRelease
│   ├── publishing/    PlatformConnection, EffectiveCapability, PublicationPlan, PublicationAttempt, Reconciliation
│   ├── analytics/     MetricDefinition, MetricSnapshot, ConversionEvent, Recommendation, RecommendationOutcome, Experiment, StrategyVersion, ModelVersion
│   ├── billing/       SubscriptionPlan, CustomerSubscription, AddOnProduct, ContentRecipe, ModelPriceSnapshot, CostEstimate, CostReservation, UsageLedgerEntry
│   ├── governance/    ToolApproval, AuditEvent, PolicyDecisionReference, AgentRegistration, ToolRegistration, ModerationDecision
│   └── support/       moderation, support cases, notifications
├── ports/         ai_text, ai_image, ai_video, ai_music, ai_speech, ai_sfx, object_storage, publishing, analytics, store_connector, music_distribution, payments
├── adapters/      concrete and fake implementations, one subpackage per port
├── workflows/     Temporal workflows and activities
├── policy/        OPA client and Rego bundle references
└── db/            SQLAlchemy models, Alembic migrations
```

`backend/tests/` mirrors this with `unit/`, `integration/` (testcontainers-python against real PostgreSQL), and `fakes/` (shared port fakes reused by contract tests).

## Dependency Direction

Matches `17_BACKEND_ARCHITECTURE.md`: `API/MCP -> Application Service -> Repository -> PostgreSQL`; `Application Service -> Port -> Adapter -> External System`; `Worker/Temporal Activity -> Application Service`. No module calls another module's repository directly — cross-module calls go through the other module's Application Service.

## Sequencing Against the Roadmap

Modules are scaffolded in Phase 1 as empty ports-and-fakes only; each phase in `23_ROADMAP_PHASES_AND_MILESTONES.md` and `milestones/` fills in exactly one or two modules with real logic. See `28_OSS_TECHNOLOGY_STACK.md` for which OSS tool is introduced in which phase.
