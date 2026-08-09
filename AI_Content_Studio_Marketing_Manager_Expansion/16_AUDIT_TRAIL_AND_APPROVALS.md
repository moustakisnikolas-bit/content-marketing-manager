# Audit Trail and Approvals

## Approval Levels

- Read: automatic when authorized
- Draft: automatic and persisted
- Paid generation: entitlement and cost reservation; confirmation by policy
- Schedule: approved content and active policy
- Publish now: explicit confirmation by default
- Distributor submission: explicit fresh confirmation plus rights
- Financial/security admin: privileged workflow, possible dual approval

## Approval Binding

Every approval binds to exact payload digest, tool/version, destination/account, cost, expiry, and approver. It is single-use.

## Authoritative Audit

PostgreSQL append-only events connect:

```text
human intent -> agent decision -> MCP tool -> OPA policy -> Temporal approval -> application action -> provider result -> cost -> reconciliation
```

## Correlation

Use request_id, correlation_id, trace_id, tool_call_id, workflow_id, and business_operation_id across gateway, OPA, Temporal, Langfuse, OpenBao, workers, and PostgreSQL.

## Auto-Pilot Audit

Record campaign policy, candidate actions, selected action, evidence, confidence, constraints, approval mode, publication outcome, and learning/evaluation version.
