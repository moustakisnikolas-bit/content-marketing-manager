# Shopify App Architecture

## App Principle

The Shopify app is a store-facing client and connector. AI intelligence remains in AI Content Studio.

## Required Building Blocks

- Shopify app registration and approved distribution model
- OAuth/token-exchange path appropriate to the selected app type
- encrypted/offline store access where required
- GraphQL Admin API adapter
- product/variant/inventory/order webhooks as approved
- mandatory compliance webhook handling for App Store distribution
- app-uninstalled cleanup
- embedded dashboard or secure redirect experience
- billing integration decision: Shopify billing versus main SaaS billing

## Webhook Reliability

- verify HMAC
- acknowledge quickly
- queue work
- deduplicate by delivery identifier
- process idempotently
- reconcile store state
- handle app scope updates and uninstall

## Store Data Boundary

Import only fields necessary for selected features. Customer/order data for abandoned-cart or audience use requires explicit feature scope, lawful basis, consent/privacy review, retention, and deletion handling.

## User Flow

```text
install -> authorize -> choose sync scope -> import products -> confirm Brand/Store Profile -> choose goal/products -> receive campaign -> approve -> generate -> publish/export -> measure
```
