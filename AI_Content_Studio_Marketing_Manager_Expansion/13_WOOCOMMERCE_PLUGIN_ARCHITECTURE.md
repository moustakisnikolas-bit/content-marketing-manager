# WooCommerce Plugin Architecture

## Thin-Plugin Principle

The WordPress/WooCommerce plugin presents store-side controls and securely communicates with AI Content Studio. AI generation, planning, publishing, analytics, billing, MCP, and recommendation logic remain in the SaaS backend.

## Plugin Responsibilities

- connect/disconnect store
- authorize and verify store ownership
- select products and campaigns
- display generated proposals/previews
- approve/edit/export/schedule
- expose sync status and safe errors
- receive signed backend callbacks where needed

## Backend Responsibilities

- API gateway/auth
- connector and product sync
- asset ingestion
- campaign generation
- publishing and analytics
- recommendations
- audit and billing

## Sync

Use WooCommerce REST capabilities plus webhooks for product/order/customer events only to the extent needed and consented. Verify webhook signatures, deduplicate deliveries, queue processing, and reconcile missed changes.

## Security

- HTTPS only
- short-lived installation handshake
- opaque store-connection identifier
- encrypted credentials/secrets
- no provider key in WordPress
- HMAC verification
- minimum required fields
- uninstall/disconnect revocation
- audit every sync and campaign action

## Plugin API

- installation handshake
- connection status
- product sync and cursor
- product selection
- campaign proposal
- preview/result retrieval
- approval and revision
- job and publishing status
- usage/billing summary

## WordPress Constraints

The plugin must remain lightweight, tolerate slow/shared hosting, use background-safe patterns, avoid blocking page requests, and display recovery steps for failed synchronization.
