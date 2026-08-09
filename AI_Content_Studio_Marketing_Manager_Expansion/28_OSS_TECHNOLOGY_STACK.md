# Open-Source Technology Stack

## Status

This file fills in the technology decisions the core spec (see `25_ULTRA_SUPER_MASTER_PROMPT.md`) deliberately leaves open. It does not override any fixed or forbidden decision from that file.

## Fixed by the Core Spec (restated, not decided here)

FastAPI modular monolith, SQLAlchemy 2.x, Alembic, PostgreSQL, Redis (broker/coordination only), Temporal, Open Policy Agent, OpenBao, Langfuse OSS, OpenTelemetry, Prometheus, Grafana. Forbidden without an approved ADR: SQLite, Oracle Database, microservices, Kubernetes, Kafka, GraphQL, CQRS, event sourcing.

## Object Storage

**SeaweedFS** (Apache-2.0, S3-compatible). MinIO Community Edition was archived in 2026; SeaweedFS is the maintained replacement and sits behind the mandated object-storage port either way.

## MCP Gateway and Registry

**IBM/mcp-context-forge** (Apache-2.0). Name-matches the spec's "MCP Gateway & Registry candidate," deployable on Docker Compose (no Kubernetes required), native OpenTelemetry export into the already-mandated observability stack.

## Frontend

- Framework: **Next.js** (App Router, TypeScript) as a REST client against `/api/v1`.
- Components: **shadcn/ui** (Radix + Tailwind) for full control of the dark, clean-card, green-accent direction without inheriting another product's visual identity.
- Dashboards/charts: **Tremor** for canned KPI/chart components, **visx** for bespoke analytics visuals (attribution, recommendation confidence).
- Data/state: **TanStack Query** (server state), **Zustand** (UI state), **React Hook Form + Zod** (wizard forms — supports auto-save/resume).
- Calendar/scheduling: **FullCalendar** (MIT core). Its resource/timeline view is a paid add-on; **Schedule-X** is the free fallback if per-account timeline views are required.
- Accessibility: `@axe-core/playwright` wired into CI as a WCAG 2.2 AA regression gate.

## Auth and Identity

Custom (Argon2 password hashing, Authlib for OAuth2 social login, JWT access tokens + a Postgres-backed refresh-token table). No external IdP through Phase 7 — `User/Organization/Workspace/Membership/Role` are already first-class Postgres entities in the spec's schema, and an external IdP would create a second source of truth against the "PostgreSQL sole authoritative store" rule. Keycloak or Ory may be introduced in Phase 8, behind a port, for enterprise client SSO only.

## Jobs and Workers

**Temporal only** — no separate Celery/arq layer. Temporal already provides idempotency, retries, dead-letter handling, and reconciliation for every queue the spec lists; a second queue system would duplicate that and risk using Redis as state storage, which is forbidden. Point Temporal Server's persistence and visibility stores at PostgreSQL. Tradeoff: Postgres-backed visibility is weaker for ad-hoc workflow search than Elasticsearch-backed visibility — report business state through `AuditEvent` and Grafana instead of Temporal's own search UI.

## Billing and Credits

Native ledger, not a third-party billing engine — `CostReservation`, `UsageLedgerEntry`, `CostEstimate`, `ModelPriceSnapshot` are already modeled as append-only Postgres entities in the spec, and a tool like Lago would introduce a second, competing billing database. **Stripe** is recommended behind the mandated payments port for card processing; no payment provider is named in the core spec, so this is an open decision, not a spec fact.

## AI and Media Generation

- Hosted text/vision: **LiteLLM Proxy**, with **OpenRouter** configured as one of its routed providers — a single OpenRouter key reaches many hosted models without separate per-vendor contracts, and stays swappable behind the port. LiteLLM's native Langfuse callback satisfies the observability requirement directly.
- Hosted inference for image/video/music/voice: **Replicate**, as the default adapter starting in Phase 2. Replicate runs hosted inference of the same open-source model classes this file also names for later self-hosting (Kokoro-class TTS, MusicGen-class music, SDXL-class image, video models), with no GPU operations burden. This closes the spec's deliberate gap on image/video provider selection.
- Later self-hosting migration (optional, same port): **Meta AudioCraft/MusicGen** (MIT code; no stable release since May 2024 — budget for in-house patching) for music/SFX; **Kokoro-82M** (Apache-2.0, commercial-safe) for voice — do not use XTTS-v2/Coqui, whose weights are non-commercial-only and can no longer be commercially licensed; **Stable Diffusion via ComfyUI** (run as a separate process, GPL-3.0 isolated from FastAPI code; verify each checkpoint's license) for image edits.
- Video generation stays Replicate-hosted regardless of hosting strategy elsewhere — no viable self-hosted option is proposed.
- Neither OpenRouter nor Replicate is open-source software; both are hosted platforms adopted because they sit cleanly behind the spec's mandated provider-neutral ports. Record this distinction in an ADR.

## Audio DSP and Media Processing

**NumPy/SciPy** for binaural/noise/sweep waveform synthesis (deterministic signal processing, not model inference — runs locally, no Replicate call needed). **Pedalboard** (Spotify's OSS effects library, MIT) for the mastering chain. **libsndfile/ffmpeg** for format handling. **FFmpeg** (subprocess, not linked) for video/image transcoding and reframing. **pyvips** for bulk image operations, **Pillow** for simple transforms.

## WooCommerce Plugin

PHP 8.1+, Composer, **Action Scheduler** (WordPress's own async-job library) for the plugin's own retry needs, PHPUnit + `wp-env` for testing. Matches the thin-plugin principle: no AI logic and no provider keys stored in WordPress.

## Shopify App

**Remix + Polaris**, Shopify's official toolchain (`@shopify/shopify-app-remix`, App Bridge). The CLI's default template ships SQLite via Prisma for local development — this must be reconfigured to PostgreSQL before staging, since SQLite is forbidden by the core spec.

## Testing

pytest + pytest-asyncio + **testcontainers-python** for real PostgreSQL integration tests (never SQLite-in-memory). One fake adapter per port, shared across contract tests, satisfying every phase's fakes requirement. Vitest + React Testing Library for frontend unit tests, **Playwright** for end-to-end, `@axe-core/playwright` for accessibility regression.

## CI/CD and Deployment

GitHub Actions for the test/build matrix. **Coolify** (Compose-based, self-hosted PaaS with rolling deploys) as the deployment target, compliant with "no Kubernetes without an ADR." Reconsider Dokploy/Docker Swarm only in Phase 8 if true multi-node scale-out becomes necessary.

## Open Risks Requiring an ADR

- Langfuse OSS self-hosting requires ClickHouse, Redis, and S3-compatible storage in addition to Postgres — this is inherent to how the mandated tool is built. Scope ClickHouse strictly to Langfuse's internal trace storage; it must never be queried by application code or hold any business-entity data of record.
- No payment provider is named in the core spec; Stripe is a recommendation.
- OpenRouter and Replicate are hosted SaaS, not open-source software; adopted for port-compatibility and to remove GPU infrastructure as a Phase 2 blocker.
- FullCalendar's resource/timeline view is a paid add-on; Schedule-X is the free fallback if needed.
