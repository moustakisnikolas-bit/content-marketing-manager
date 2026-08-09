# Auto-Pilot Marketing Mode

## Purpose

Auto-Pilot creates and executes marketing plans inside user-approved boundaries. It is bounded autonomy, not unrestricted publishing.

## Automation Levels

- Manual: user chooses content and time.
- Guided: system proposes; user confirms.
- Scheduled Autonomy: user approves content; system chooses eligible time.
- Plan Autonomy: user approves a campaign plan and guardrails; system creates/schedules inside them.

## Guardrails

- allowed brands/products
- allowed platforms and accounts
- campaign period
- monthly content and spend limits
- allowed formats and tones
- blocked topics and claims
- approval frequency
- posting windows and daily caps
- repetition/diversity rules
- stop conditions
- kill switch

## Auto-Pilot Cycle

```text
analyze inventory/performance
-> propose monthly plan
-> validate cost/eligibility
-> generate previews
-> request approvals according to policy
-> create finals
-> select slots
-> publish
-> collect outcomes
-> explain improvements
```

## Mandatory Controls

- OPA policy decision
- Temporal approval workflow
- append-only audit
- exact payload approval binding
- cost reservation
- platform capability validation
- content moderation and rights checks
- duplicate/repetition prevention
- reconciliation before retry
