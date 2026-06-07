"""Subagent tests for scoped tools, structured outputs, and write isolation."""

from pathlib import Path
import asyncio

from patchpilot.config import PatchPilotConfig
from patchpilot.errors import ModelResponseError
from patchpilot.models.base import ModelClient, ModelJsonResponse, ToolSelection
from patchpilot.runtime.subagents import SUBAGENT_CONFIGS, SubagentRuntime
from patchpilot.tools import build_registry
from patchpilot.tools.executor import ToolExecutor
from patchpilot.tools.registry import ToolContext


def test_subagent_tool_returns_valid_shape(tmp_path: Path) -> None:
    context = ToolContext(repo_root=tmp_path, config=PatchPilotConfig(repo=tmp_path))
    executor = ToolExecutor(build_registry())

    output = asyncio.run(
        executor.execute(
            "subagent.spawn_diagnosis",
            {"task": "diagnose", "context": {"output": "failure"}},
            context,
        )
    )

    assert output.name == "diagnosis"
    assert output.status == "success"
    assert output.result["scoped"] is True
    assert output.result["recommended_patch_direction"]
    assert "fs.apply_patch" not in output.result["config"]["allowed_tools"]


def test_review_subagent_is_read_only(tmp_path: Path) -> None:
    context = ToolContext(repo_root=tmp_path, config=PatchPilotConfig(repo=tmp_path))
    executor = ToolExecutor(build_registry())

    output = asyncio.run(
        executor.execute(
            "subagent.spawn_review",
            {"task": "review", "context": {"patch_plan": {"summary": "none"}}},
            context,
        )
    )

    assert output.name == "review"
    assert output.result["approved"] is True
    assert "fs.apply_patch" not in output.result["config"]["allowed_tools"]
    assert "fs.write_file" not in output.result["config"]["allowed_tools"]


def test_diagnosis_subagent_allows_read_only_discovery_tools() -> None:
    allowed = set(SUBAGENT_CONFIGS["diagnosis"].allowed_tools)

    assert "fs.list_dir" in allowed
    assert "fs.glob" in allowed
    assert "fs.apply_patch" not in allowed
    assert "fs.write_file" not in allowed
    assert "exec.run_tests" not in allowed


def test_model_subagent_records_bad_read_without_crashing(tmp_path: Path) -> None:
    context = ToolContext(repo_root=tmp_path, config=PatchPilotConfig(repo=tmp_path))
    model = BadReadDiagnosisModel()

    output = asyncio.run(
        SubagentRuntime(model=model).run(
            kind="diagnosis",
            task="diagnose",
            parent_context=context,
            evidence={"output": "tests/test_app.py:1: AssertionError"},
        )
    )

    assert output.status == "success"
    assert output.result["root_cause"] == "bad read was recoverable"
    assert output.result["evidence"]["model_tool_1"]["error_type"] == "FileNotFoundError"


def test_diagnosis_retries_with_repo_grounded_candidates(tmp_path: Path) -> None:
    _write_diagnosis_fixture(tmp_path)
    context = ToolContext(repo_root=tmp_path, config=PatchPilotConfig(repo=tmp_path))
    model = WrongPathThenRecoverModel()

    output = asyncio.run(
        SubagentRuntime(model=model).run(
            kind="diagnosis",
            task="diagnose entitlement failure",
            parent_context=context,
            evidence={
                "failing_output": "FAILED tests/test_events.py::test_normalizes_delta\n"
                "tests/test_events.py:4: AssertionError",
                "source_file_hints": ["entitlements/events.py", "entitlements/ledger.py"],
            },
        )
    )

    assert output.status == "success"
    assert output.result["root_cause"] == "recovered from wrong path"
    assert output.result["recovery"]["used"] is True
    assert output.result["recovery"]["fallback_used"] is False
    assert "entitlements/events.py" in _normalized_paths(output.result["implicated_files"])
    assert _normalized_paths(output.result["evidence"]["model_tool_1"]["output"]["missing_files"]) == ["src/events.py"]
    assert output.result["evidence"]["model_tool_2"]["tool"] == "fs.list_dir"
    assert output.result["evidence"]["model_tool_3"]["tool"] == "fs.glob"
    assert output.result["evidence"]["retry_model_tool_1"]["tool"] == "fs.read_files"


def test_diagnosis_falls_back_to_low_confidence_when_retry_fails(tmp_path: Path) -> None:
    _write_diagnosis_fixture(tmp_path)
    context = ToolContext(repo_root=tmp_path, config=PatchPilotConfig(repo=tmp_path))

    output = asyncio.run(
        SubagentRuntime(model=AlwaysEmptyDiagnosisModel()).run(
            kind="diagnosis",
            task="diagnose entitlement failure",
            parent_context=context,
            evidence={
                "failing_output": "FAILED tests/test_events.py::test_normalizes_delta\n"
                "tests/test_events.py:4: AssertionError",
                "source_file_hints": ["entitlements/events.py"],
            },
        )
    )

    assert output.status == "success"
    assert output.result["confidence"] == 0.35
    assert output.result["recovery"]["fallback_used"] is True
    assert "entitlements/events.py" in _normalized_paths(output.result["implicated_files"])
    assert output.result["evidence"]["diagnosis_recovery"]["sufficient_evidence"] is True


class BadReadDiagnosisModel(ModelClient):
    provider = "openrouter"

    async def select_tool(self, state, tools):
        if not state.tool_history:
            return ToolSelection(tool_name="fs.read_file", arguments={"path": "missing.py"}, rationale="bad path")
        return ToolSelection(finish=True, rationale="done")

    async def complete_json(self, *, prompt, schema_name, json_schema):
        return ModelJsonResponse(
            data={
                "root_cause": "bad read was recoverable",
                "evidence": prompt["tool_evidence"],
                "evidence_links": [],
                "implicated_files": [],
                "shared_root_cause": "bad read was recoverable",
                "recommended_patch_direction": "continue with available evidence",
                "confidence": 0.5,
                "risks": [],
            }
        )


class WrongPathThenRecoverModel(ModelClient):
    provider = "openrouter"

    def __init__(self) -> None:
        self.tool_calls = 0
        self.structured_calls = 0

    async def select_tool(self, state, tools):
        self.tool_calls += 1
        prompt_context = state.last_text_output + str(state.working_set.model_dump(mode="json"))
        assert "entitlements/events.py" in prompt_context
        if self.tool_calls == 1:
            return ToolSelection(
                tool_name="fs.read_files",
                arguments={"paths": ["tests/test_events.py", "src/events.py"]},
                rationale="first guess uses a common src layout",
            )
        if self.tool_calls == 2:
            return ToolSelection(tool_name="fs.list_dir", arguments={"path": "."}, rationale="discover repo root")
        if self.tool_calls == 3:
            return ToolSelection(tool_name="fs.glob", arguments={"pattern": "entitlements/*.py"}, rationale="discover package files")
        if self.tool_calls == 4:
            assert "Use only existing paths from source_candidates" in state.last_text_output
            return ToolSelection(
                tool_name="fs.read_files",
                arguments={"paths": ["entitlements/events.py", "entitlements/ledger.py"]},
                rationale="read recovered candidates",
            )
        return ToolSelection(finish=True, rationale="done")

    async def complete_json(self, *, prompt, schema_name, json_schema):
        self.structured_calls += 1
        if self.structured_calls == 1:
            raise ModelResponseError("OpenRouter returned empty message content")
        recovery = prompt["evidence"]["diagnosis_recovery"]
        assert "entitlements/events.py" in recovery["source_candidates"]
        assert prompt["tool_evidence"]["retry_model_tool_1"]["output"]["files"]
        return ModelJsonResponse(
            data={
                "root_cause": "recovered from wrong path",
                "evidence": prompt["tool_evidence"],
                "evidence_links": [],
                "implicated_files": ["entitlements/events.py"],
                "shared_root_cause": "recovered from wrong path",
                "recommended_patch_direction": "patch the recovered source candidate",
                "confidence": 0.7,
                "risks": [],
            }
        )


class AlwaysEmptyDiagnosisModel(ModelClient):
    provider = "openrouter"

    async def select_tool(self, state, tools):
        return ToolSelection(finish=True, rationale="provider cannot respond")

    async def complete_json(self, *, prompt, schema_name, json_schema):
        raise ModelResponseError("OpenRouter returned empty message content")


def _write_diagnosis_fixture(root: Path) -> None:
    package = root / "entitlements"
    tests = root / "tests"
    package.mkdir()
    tests.mkdir()
    (package / "__init__.py").write_text("from .events import normalize_delta\n", encoding="utf-8")
    (package / "events.py").write_text(
        "def normalize_delta(value: int) -> int:\n"
        "    return value\n",
        encoding="utf-8",
    )
    (package / "ledger.py").write_text(
        "def apply_delta(current: int, delta: int) -> int:\n"
        "    return current + delta\n",
        encoding="utf-8",
    )
    (tests / "test_events.py").write_text(
        "from entitlements import normalize_delta\n\n\n"
        "def test_normalizes_delta():\n"
        "    assert normalize_delta(-1) == 0\n",
        encoding="utf-8",
    )


def _normalized_paths(paths) -> list[str]:
    return [str(path).replace("\\", "/") for path in paths]
