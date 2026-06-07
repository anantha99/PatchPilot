"""Prompt-layer builders that separate stable instructions from volatile run state."""

from __future__ import annotations

from typing import Any


PHASE_INSTRUCTIONS = {
    "inspect": "Inspect the repo. Prefer fs.list_dir, code.detect_language, code.detect_package_manager, code.find_tests, exec.detect_test_command, then session.mark_phase reproduce.",
    "reproduce": "Run the supplied or detected tests to capture the failing output, then mark phase diagnose.",
    "diagnose": "Extract failure locations and spawn the diagnosis subagent with the failing output, then record an observation and mark phase plan_patch.",
    "plan_patch": "Map failing tests to source, read the failing test and implicated source files. PatchPilot will ask you for a typed PatchPlan once enough file evidence is present.",
    "apply_patch": "Apply the validated stored patch plan. Call fs.apply_patch with the patch from the patch_plan artifact when it appears in recent history.",
    "validate": "Run targeted tests first, then full tests, then capture git.diff and mark phase review.",
    "review": "Spawn the review subagent, summarize/retrieve artifacts, then mark phase report.",
    "report": "Collect command history, export session memory, then finish.",
}


def tool_selection_prompt(state: Any, tools: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "stable": {
            "role": "tool-selection",
            "phase_instructions": PHASE_INSTRUCTIONS,
            "tool_contract": {
                "shape": {"tool_name": "string|null", "arguments": "object", "rationale": "string", "finish": "boolean"},
                "tools": tools,
            },
        },
        "volatile": {
            "goal": state.goal,
            "phase": state.phase,
            "phase_instruction": PHASE_INSTRUCTIONS.get(state.phase, ""),
            "test_command": state.test_command,
            "validation_status": state.validation_status,
            "attempt": state.attempt,
            "working_set": state.working_set.model_dump(mode="json") if hasattr(state, "working_set") else {},
            "attempts": [attempt.model_dump(mode="json") for attempt in getattr(state, "attempts", [])],
            "recent_tool_calls": state.tool_history[-8:],
            "last_command_output": _truncate(state.last_command_output, 6000),
            "last_text_output": _truncate(state.last_text_output, 4000),
        },
    }


def structured_json_prompt(*, schema_name: str, json_schema: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    instructions = [
        f"Return only JSON matching the {schema_name} schema.",
        "Do not include markdown.",
        "Use repository-relative paths.",
    ]
    if schema_name == "PatchPlan":
        instructions.extend(
            [
                "Treat edits[].before as a strict SEARCH block: copy the exact current text from the file evidence.",
                "Treat edits[].after as the REPLACE block: include the exact replacement text.",
                "Do not rely on unified diff hunk line counts; leave patch empty unless you are certain it is valid.",
                "PatchPilot will apply structured edits and generate the clean diff locally.",
            ]
        )
    return {
        "stable": {
            "role": "structured-json",
            "schema_name": schema_name,
            "json_schema": json_schema,
            "instructions": instructions,
        },
        "volatile": task,
    }


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]
