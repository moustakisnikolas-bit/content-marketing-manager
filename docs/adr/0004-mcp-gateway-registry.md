# ADR-0004: MCP Gateway and Registry Implementation

## Status
Proposed

## Context
The core spec names "MCP Gateway & Registry" as a candidate for agent/tool governance (Phase 7) but does not commit to a specific implementation. Two real open-source projects match the name: IBM/mcp-context-forge (Apache-2.0, originally named "MCP Gateway & Registry," now branded ContextForge) and agentic-community/mcp-gateway-registry (Apache-2.0, formerly AWS-incubated, closer literal name match but defaults to Cognito/Keycloak/Entra identity integration).

## Decision
Adopt IBM/mcp-context-forge. It federates MCP/A2A/REST/gRPC behind one endpoint, exports OpenTelemetry natively into the already-mandated OTel/Prometheus/Grafana stack, and deploys on plain Docker/Docker Compose without requiring Kubernetes. Its identity model does not assume an external IdP, which matches this project's custom-auth decision (identity stays Postgres-authoritative through at least Phase 7).

## Consequences
- Both candidate projects are relatively young infrastructure; pin versions and treat the gateway as replaceable — application code only ever talks to MCP through the Application Service layer, never directly, so a future swap stays contained.
- Revisit this ADR if IBM/mcp-context-forge's maintenance status changes materially before Phase 7 begins.
