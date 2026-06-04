"""Context compaction utilities."""

from __future__ import annotations

from patchpilot.runtime.state import SessionState


def compact_state(state: SessionState, keep_recent: int = 8) -> dict:
    preserved = {}
    for item in state.tool_history:
        name = item.get("tool_name")
        if name in {
            "exec.run_tests",
            "exec.run_targeted_tests",
            "subagent.spawn_diagnosis",
            "subagent.spawn_review",
            "code.validate_patch_shape",
            "fs.apply_patch",
            "git.diff",
        }:
            preserved[name] = item.get("output")
    return {
        "goal": state.goal,
        "phase": state.phase,
        "recent_tool_history": state.tool_history[-keep_recent:],
        "tool_call_count": len(state.tool_history),
        "attempt": state.attempt,
        "validation_status": state.validation_status,
        "preserved_artifacts": preserved,
    }
