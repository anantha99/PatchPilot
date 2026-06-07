"""Context compaction utilities that preserve typed repair artifacts."""

from __future__ import annotations

from patchpilot.runtime.state import SessionState


def compact_state(state: SessionState, keep_recent: int = 8) -> dict:
    """Preserve typed artifacts while clipping bulky command/file output."""
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
    recent = [_compact_history_item(item) for item in state.tool_history[-keep_recent:]]
    return {
        "goal": state.goal,
        "phase": state.phase,
        "recent_tool_history": recent,
        "tool_call_count": len(state.tool_history),
        "attempt": state.attempt,
        "validation_status": state.validation_status,
        "working_set": state.working_set.model_dump(mode="json"),
        "attempts": [attempt.model_dump(mode="json") for attempt in state.attempts],
        "rejected_patch_plans": state.rejected_patch_plans,
        "model_metadata": state.model_metadata,
        "preserved_artifacts": preserved,
    }


def _compact_history_item(item: dict) -> dict:
    output = item.get("output")
    if not isinstance(output, dict):
        return item
    compacted = dict(output)
    for key in ("stdout", "stderr", "content", "patch"):
        value = compacted.get(key)
        if isinstance(value, str) and len(value) > 1200:
            compacted[key] = value[-1200:]
            compacted[f"{key}_truncated"] = True
    return {**item, "output": compacted}
