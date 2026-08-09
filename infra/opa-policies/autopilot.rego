package content_studio.autopilot

import future.keywords.contains
import future.keywords.if
import future.keywords.in

# Phase 4's first real guardrail policy — evaluated before every Auto-Pilot
# action (see workflows/autopilot.py). Mirrors the guardrail list from
# 08_AUTOPILOT_MARKETING_MODE.md: allowed platforms, spend limit, blocked
# topics, posting window, kill switch. `allow` is derived from
# `deny_reasons` rather than the other way around, so every rejection
# always carries an explanation — never a bare "false".

default allow := false

allow if {
	count(deny_reasons) == 0
}

deny_reasons contains "the kill switch is active" if {
	input.kill_switch_active
}

deny_reasons contains sprintf("platform %v is not in the allowed platform list", [input.platform]) if {
	not input.platform in input.allowed_platforms
}

deny_reasons contains "this action would exceed the campaign's spend limit" if {
	to_number(input.spend_used) + to_number(input.estimated_next_cost) > to_number(input.spend_limit)
}

deny_reasons contains sprintf("current hour %v is before the allowed posting window starts at %v", [input.current_hour, input.window_start_hour]) if {
	input.current_hour < input.window_start_hour
}

deny_reasons contains sprintf("current hour %v is after the allowed posting window ends at %v", [input.current_hour, input.window_end_hour]) if {
	input.current_hour > input.window_end_hour
}

deny_reasons contains sprintf("the brief text mentions a blocked topic: %v", [topic]) if {
	some topic in input.blocked_topics
	contains(lower(input.topic_text), lower(topic))
}
