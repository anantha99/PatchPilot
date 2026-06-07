"""Deterministic model scripts used by tests and smoke evals."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from patchpilot.models.base import ModelClient, ModelJsonResponse, ToolSelection


class FakeModelClient(ModelClient):
    """A deterministic model that still chooses tools through the public contract."""

    provider = "fake"

    def __init__(self) -> None:
        self.index = 0

    async def select_tool(self, state: Any, tools: list[dict[str, Any]]) -> ToolSelection:
        script = self._script(state)
        if self.index >= len(script):
            return ToolSelection(finish=True, rationale="script complete")
        tool_name, arguments, rationale = script[self.index]
        self.index += 1
        return ToolSelection(tool_name=tool_name, arguments=arguments, rationale=rationale)

    def _script(self, state: Any) -> list[tuple[str, dict[str, Any], str]]:
        source = "buggy_math/calculator.py"
        test = "tests/test_calculator.py"
        before = "def add(a: int, b: int) -> int:\n    return a - b\n"
        after = "def add(a: int, b: int) -> int:\n    return a + b\n"
        patch = (
            "diff --git a/buggy_math/calculator.py b/buggy_math/calculator.py\n"
            "--- a/buggy_math/calculator.py\n"
            "+++ b/buggy_math/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def add(a: int, b: int) -> int:\n"
            "-    return a - b\n"
            "+    return a + b\n"
        )
        command = state.test_command or "pytest"
        targeted_command = f"pytest {test}" if command == "pytest" else command
        return [
            ("session.mark_phase", {"phase": "inspect"}, "start inspect phase"),
            ("fs.list_dir", {"path": "."}, "inspect repository root"),
            ("code.detect_language", {"path": "."}, "detect language"),
            ("code.detect_package_manager", {"path": "."}, "detect package manager"),
            ("code.find_tests", {"path": "."}, "find tests"),
            ("exec.detect_test_command", {}, "detect test command"),
            ("session.mark_phase", {"phase": "reproduce"}, "start reproduce phase"),
            ("exec.run_tests", {"command": command}, "reproduce failing test"),
            ("session.mark_phase", {"phase": "diagnose"}, "start diagnose phase"),
            ("code.extract_failure_locations", {"output": state.last_command_output}, "extract failure locations"),
            ("subagent.spawn_diagnosis", {"task": "diagnose pytest failure", "context": {"output": state.last_command_output}}, "isolate diagnosis"),
            ("session.record_observation", {"text": "pytest failure points at add returning subtraction", "tags": ["diagnosis"]}, "record diagnosis observation"),
            ("session.mark_phase", {"phase": "plan_patch"}, "start patch planning"),
            ("code.map_test_to_source", {"path": test}, "map failing test to source"),
            ("fs.read_file", {"path": source}, "read source"),
            ("fs.read_file", {"path": test}, "read test"),
            ("session.store_artifact", {"key": "patch_plan", "value": {"task_classification": "source_fix", "root_cause": "add subtracts", "evidence_refs": [test, source], "planned_changed_files": [source], "edits": [{"path": source, "before": before, "after": after, "evidence_refs": [test, source], "purpose": "Fix the arithmetic contract exercised by the failing pytest.", "expected_validation": [targeted_command, command], "root_cause_linkage": "The changed source line is the implementation of the failing add contract."}], "patch": patch, "summary": "Change add to return sum."}}, "store patch plan"),
            ("code.validate_patch_shape", {"task_classification": "source_fix", "target_files": [source], "max_diff_lines": 200}, "validate patch shape"),
            ("session.record_decision", {"decision": "apply_patch", "reason": "patch plan validated and only touches source file"}, "record write gate decision"),
            ("session.mark_phase", {"phase": "apply_patch"}, "start apply phase"),
            ("fs.apply_patch", {"patch": patch}, "apply validated patch"),
            ("session.mark_phase", {"phase": "validate"}, "start validation phase"),
            ("exec.run_targeted_tests", {"command": targeted_command}, "run targeted validation"),
            ("exec.run_tests", {"command": command}, "run full validation"),
            ("git.diff", {}, "capture final diff"),
            ("session.mark_phase", {"phase": "review"}, "start review phase"),
            ("subagent.spawn_review", {"task": "review final diff", "context": {"diff": state.last_text_output}}, "review patch"),
            ("session.summarize_context", {"observations": ["source fix applied", "targeted tests passed", "full tests passed"], "max_chars": 1000}, "compact context"),
            ("session.retrieve_artifacts", {"keys": ["patch_plan", "subagents", "phases"]}, "retrieve structured artifacts"),
            ("session.mark_phase", {"phase": "report"}, "start report phase"),
            ("exec.command_history", {}, "collect command history"),
            ("session.export_session", {}, "export session memory"),
        ]

    async def complete_json(
        self,
        *,
        prompt: dict[str, Any],
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> ModelJsonResponse:
        return ModelJsonResponse(data={})
