package content_studio.authz

import future.keywords.if

# Phase 1 placeholder: proves the OPA integration path (Application Service ->
# OPA client -> this bundle) works end-to-end. Real guardrail policies
# (Auto-Pilot limits in Phase 4, tool/agent risk levels in Phase 7) replace
# this with per-domain rule files.

default allow := false

allow if {
	input.action == "health_check"
}
