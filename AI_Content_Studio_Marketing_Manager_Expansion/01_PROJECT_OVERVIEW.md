# Project Overview

## Product Definition

AI Content Studio is an ultra beginner-friendly marketing operations platform for small businesses, creators, freelancers, eCommerce stores, agencies, and local businesses.

It combines:

- AI Content Studio,
- AI Marketing Manager,
- Audio Studio,
- AI eCommerce Manager,
- publishing and distribution,
- analytics and optimization,
- MCP tools and governed agents,
- subscriptions, credits, add-ons, and agency capabilities.

## Product Journey

```text
Business Goal or Product
-> Guided Marketing Brief
-> Campaign Proposal
-> Preview and Cost Estimate
-> Approval
-> Content Generation
-> Scheduling and Publishing
-> Analytics and Attribution
-> Explainable Recommendations
-> Improvement or Repurposing
```

## Experience Standard

The user should never feel lost. Every complex action must become a simple explanation, clear button, guided decision, preview, approval summary, and safe next step.

## Fixed Technical Decisions

- FastAPI modular monolith
- PostgreSQL as authoritative business database
- Redis for broker and temporary coordination only
- private object storage
- provider-neutral adapters
- Temporal for durable approvals/workflows
- OPA for policy decisions
- MCP Gateway & Registry candidate for MCP governance
- Langfuse OSS for agent observability
- OpenBao for secrets
- PostgreSQL append-only authoritative business audit
