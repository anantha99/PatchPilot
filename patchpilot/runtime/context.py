"""Context compaction utilities."""

from __future__ import annotations

from patchpilot.runtime.state import SessionState


def compact_state(state: SessionState, keep_recent: int = 8) -> dict:
    return {
        "goal": state.goal,
        "phase": state.phase,
        "recent_tool_history": state.tool_history[-keep_recent:],
        "tool_call_count": len(state.tool_history),
    }
