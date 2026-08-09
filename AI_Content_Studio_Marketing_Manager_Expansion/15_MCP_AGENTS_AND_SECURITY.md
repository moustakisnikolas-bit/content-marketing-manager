# MCP, Agents, and Security

## Selected Open-Source Stack

- MCP Gateway & Registry candidate
- Open Policy Agent
- Temporal
- Langfuse OSS
- OpenBao
- OpenTelemetry, Prometheus, Grafana
- PostgreSQL authoritative audit

## New Agents

- Marketing Manager Agent
- Campaign Planner Agent
- Creation Coordinator Agent
- Publishing Agent
- Analytics/Recommendation Agent
- eCommerce Agent
- Audio Guide Agent
- Support Agent

## MCP Domains

- knowledge
- marketing
- planning
- commerce
- generation
- audio
- connections
- publishing
- analytics
- distribution
- billing
- support

## Security Rules

- tools wrap application services
- no raw SQL/arbitrary HTTP
- tenant context injected by authenticated host
- user, agent, MCP, service, and platform identities separated
- tool/version allowlists
- risk levels and OPA decisions
- explicit approval for high-impact actions
- no OAuth token through LLM
- untrusted content never treated as instruction
- full redacted correlated audit
