# AI Content Studio — Ultra Super Analytical Master Prompt

## Authority

This is the active product implementation prompt. It preserves all approved AI Content Studio, Audio Studio, publishing, MCP, security, audit, open-source integration, beginner-experience, and commercial requirements and adds AI Marketing Manager and AI eCommerce Manager.

## Mission

Implement an ultra beginner-friendly AI Content Studio that evolves into an AI Marketing Manager. Guide a user from zero knowledge to measurable, approved, and published marketing output.

## Mandatory Positioning

The user does not merely request a post. The user supplies a product, service, offer, event, link, image, brand idea, store item, or campaign objective. The platform recommends and coordinates the message, format, platform, creative direction, CTA, timing, campaign structure, variants, approvals, publication, analytics, and improvement.

## Beginner Mandate

The user must never feel lost. Translate every complex action into simple explanations, guided decisions, clear buttons, safe defaults, previews, cost visibility, and next steps. Support users who do not know marketing, AI, design, editing, music production, social strategy, integrations, or eCommerce automation.

## Product Modules

- AI Content Creation
- Audio Studio
- AI Marketing Manager
- Auto-Pilot Marketing
- Campaigns and Calendar
- Social Publishing
- Analytics and Optimization
- Recommendation Engine
- AI eCommerce Manager
- WooCommerce Connector/Plugin
- Shopify App
- MCP Agents and Security
- Audit and Approvals
- Billing and Credits
- Agency and future white label

## AI Marketing Manager

Implement a goal-based wizard, Marketing Brief, Campaign Proposal, campaign recipes, required assets, content calendar, platform/format/tone/CTA recommendations, creative variants, estimated use, beginner explanation, internal evidence, approval, execution, outcomes, and repurposing.

The campaign proposal never claims certainty. It identifies assumptions, evidence, confidence, missing data, and measurable objective definitions.

## Auto-Pilot

Auto-Pilot is bounded by allowed products, accounts, platforms, formats, schedules, volumes, costs, tones, blocked claims, approvals, stop conditions, and kill switch. It cannot bypass rights, moderation, platform capability, OPA policy, Temporal approval, cost reservation, or audit.

## Recommendation Engine

Use owned authorized history and store signals. Begin with deterministic/statistical methods. Each recommendation stores evidence, score, confidence, sample size, period, objective, strategy version, expiry, and simple explanation. Do not invent metrics or claim causation without evidence.

## eCommerce

Keep AI logic in the SaaS backend. WooCommerce and Shopify clients perform authorization, product selection, sync status, previews, approval, and result display. Implement least-privilege product/variant/asset/price/stock/category/tag/SKU/URL sync, authenticated webhooks, idempotency, uninstall/revocation, reconciliation, and privacy controls.

Customer/order data features require explicit scope, lawful basis, consent/privacy review, minimization, retention, and deletion handling.

## Architecture

Use FastAPI modular monolith, PostgreSQL, SQLAlchemy 2.x, Alembic, Redis for broker/coordination only, private object storage, workers, REST `/api/v1`, provider-neutral adapters, Temporal, OPA, MCP Gateway & Registry candidate, Langfuse OSS, OpenBao, OpenTelemetry, Prometheus, Grafana, and PostgreSQL authoritative audit.

## Backend Modules

Identity, workspaces, brands, products/services, stores/connectors, marketing goals/briefs/campaigns, planning, content/assets/generation, Audio Studio, reviews, platform connections, publishing, analytics/attribution/recommendations/experiments, subscriptions/credits/costs, MCP/agents/policy/approvals/audit/moderation/support.

## Security

Separate user, agent, MCP, service, and external identities. MCP tools wrap application services and never expose raw SQL, arbitrary HTTP, filesystem, or credentials. Use tool/version allowlists, OPA policies, risk levels, exact-payload approvals, OpenBao secrets, audit correlation, prompt-injection isolation, quotas, rate limits, egress restrictions, and fail-closed high-risk actions.

## Audit

Create append-only business events for intent, agent/tool choice, policy decision, approval, execution, provider result, cost, retry, reconciliation, moderation, and outcome. Correlate gateway, OPA, Temporal, Langfuse, OpenBao, app, workers, and providers.

## Commercial

Support monthly plans, Content Credits, add-ons, revisions, pay-per-extra generation, eCommerce plans, agency plans, and future white-label/reseller. Every job reserves cost/entitlement before dispatch and settles actual use afterwards.

## Platform Integrations

Enable capabilities only when supported by official APIs, connected account, granted scopes, app approval, and current restrictions. Provide transparent export/manual fallback when direct capability is unavailable.

## Implementation Discipline

Work on one milestone at a time. For each milestone provide scope, non-scope, beginner/admin journeys, architecture, domain/state model, schema/migration, APIs, MCP contracts, jobs, security, cost, audit, UI copy, tests, commands, risks, and acceptance criteria.

Do not use SQLite or Oracle Database. Do not introduce microservices, Kubernetes, Kafka, GraphQL, CQRS, or event sourcing without an approved ADR. Do not claim deployment or compatibility without evidence. Stop after the active milestone.
