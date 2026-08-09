# PostgreSQL Schema

## Core

User, Organization, Workspace, Membership, Role, BrandProfile, BrandRule

## Commerce

StoreConnection, StoreCapability, StoreSyncCursor, Product, ProductVariant, ProductAsset, ProductPerformanceSnapshot, StoreWebhookDelivery

## Marketing

MarketingGoal, MarketingBrief, CampaignProposal, Campaign, CampaignPlanItem, CampaignVariant, CampaignDecision, CampaignOutcome, AutoPilotPolicy

## Content

ContentItem, ContentRevision, ContentPackage, Review, Asset, AssetRelationship, GenerationJob, GenerationAttempt

## Audio

AudioAlbum, AudioTrack, AudioComposition, AudioLayer, FrequencySegment, MusicRelease, TrackRelease

## Publishing

PlatformConnection, EffectiveCapability, PublicationPlan, PublicationAttempt, Reconciliation

## Intelligence

MetricDefinition, MetricSnapshot, ConversionEvent, Recommendation, RecommendationOutcome, Experiment, StrategyVersion, ModelVersion

## Commercial

SubscriptionPlan, CustomerSubscription, AddOnProduct, ContentRecipe, ModelPriceSnapshot, CostEstimate, CostReservation, UsageLedgerEntry

## Governance

ToolApproval, AuditEvent, PolicyDecisionReference, AgentRegistration, ToolRegistration, ModerationDecision, SupportCase

## Rules

- UUID primary keys
- UTC timezone-aware timestamps
- explicit tenant ownership
- Decimal money
- immutable attempts and decisions
- JSONB only for variable metadata
- unique idempotency keys
- indexes on tenant/status/time/foreign references
- append-only audit permissions
