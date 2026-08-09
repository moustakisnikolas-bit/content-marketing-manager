package content_studio.mcp_tools

import future.keywords.contains
import future.keywords.if

# Phase 7's tool/agent risk-level allowlisting policy — evaluated before
# every MCP tool call (see modules/governance/tool_governance.py). Same
# deny_reasons-derives-allow pattern as autopilot.rego: every rejection
# carries an explanation, never a bare "false".

default allow := false

allow if {
	count(deny_reasons) == 0
}

deny_reasons contains "the agent is not registered or is disabled" if {
	input.agent_status != "active"
}

deny_reasons contains "the tool is not registered (this name/version) or is disabled" if {
	input.tool_status != "active"
}

deny_reasons contains "high-risk tools require a valid, unused, unexpired approval" if {
	input.risk_level == "high"
	not input.has_valid_approval
}

deny_reasons contains "untrusted input content was flagged by moderation and cannot be used to instruct a tool call" if {
	input.moderation_blocked
}
