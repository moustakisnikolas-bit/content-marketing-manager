# ADR-0002: Payment Provider Selection

## Status
Proposed

## Context
The core spec defines a credit-based reserve -> settle -> release billing ledger as native, Postgres-authoritative business entities (`SubscriptionPlan`, `CustomerSubscription`, `CostReservation`, `UsageLedgerEntry`) but does not name a payment processor for actual card/subscription charging. The spec mandates a provider-neutral `payments` port for whichever processor is chosen.

## Decision
Adopt Stripe as the initial payments adapter behind the `payments` port: strong subscriptions and metered-billing primitives, broad card/SCA support, good fit for the draft EUR pricing tiers in `22_BILLING_AND_PRICING_MODEL.md`. Stripe is never the ledger of record — it only executes charges/refunds that the native ledger has already reserved and settled.

## Consequences
- Stripe fees become one of the cost categories tracked per `21_PROVIDER_STRATEGY_AND_COSTS.md`.
- Because the integration sits behind a port, a regional PSP (e.g., Mollie/Adyen) can be added or substituted later without touching ledger logic.
- Re-evaluate if EU-specific payment method coverage or fees make a regional PSP preferable before launch.
