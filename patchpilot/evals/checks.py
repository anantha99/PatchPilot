"""Shared eval checks for trace-derived assignment proof."""

from __future__ import annotations

from typing import Any


def trace_tool_checks(events: list[Any], *, min_tool_calls: int) -> dict[str, bool]:
    completed = [event for event in events if event.event_type == "tool.completed"]
    model_events = [event for event in events if event.event_type == "model.tool_selection"]
    child_events = [event for event in events if event.event_type.startswith("subagent.")]
    return {
        "min_tool_calls": len(completed) >= min_tool_calls,
        "subagent": any(event.name.startswith("subagent.") for event in completed),
        "model_selection": len(model_events) > 0,
        "subagent_child_spans": any(event.event_type == "subagent.started" for event in child_events)
        and any(event.event_type == "subagent.completed" for event in child_events),
    }


def ordered_phases(events: list[Any], expected: list[str]) -> bool:
    observed = [event.name for event in events if event.event_type == "plan.updated"]
    positions = [expected.index(phase) for phase in observed if phase in expected]
    return bool(positions) and positions == sorted(positions)
