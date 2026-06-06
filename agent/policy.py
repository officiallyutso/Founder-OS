"""Tiered autonomy / risk policy.

Centralizes the "should I just do this, ask first, or refuse?" decision so it isn't
scattered through the loop. Decision depends on the tool's risk and the configured
autonomy level:

  - cautious    : approval-gated tools AND state-changing writes need approval
  - balanced    : approval-gated tools need approval (default)
  - autonomous  : nothing is gated (equivalent to AUTO_APPROVE) - high trust

Returns one of: 'allow' (execute now), 'approve' (queue for the founder), 'deny'.
"""
from config import config

# Tools that change external/world state but aren't in the hard approval set.
_WRITE_TOOLS = {
    "add_contact", "update_contact_status", "set_followup", "add_task",
    "calendar_create_event", "set_reminder", "add_goal", "graph_link",
}


def decide(tool, args: dict) -> str:
    if tool is None:
        return "allow"
    level = (config.autonomy_level or "balanced").lower()

    if getattr(tool, "requires_approval", False):
        if level == "autonomous" or config.auto_approve:
            return "allow"
        return "approve"

    if level == "cautious" and tool.name in _WRITE_TOOLS:
        return "approve"

    return "allow"
