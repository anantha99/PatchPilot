from pathlib import Path
import asyncio
import json
import shutil
import sys

from patchpilot.config import PatchPilotConfig
from patchpilot.models.base import ModelClient, ModelJsonResponse, ToolSelection
from patchpilot.models.fake import FakeModelClient
from patchpilot.runtime.graph import RepairRuntime


COPY_IGNORE = shutil.ignore_patterns(".patchpilot", ".pytest_cache", "__pycache__")


class CommandOnlyModel(ModelClient):
    def __init__(self, command: str) -> None:
        self.command = command
        self.index = 0

    async def select_tool(self, state, tools):
        script = [
            ToolSelection(tool_name="memory_eval.mark_phase", arguments={"phase": "reproduce"}, rationale="start reproduce"),
            ToolSelection(tool_name="exec.run_tests", arguments={"command": self.command}, rationale="run supplied command"),
        ]
        if self.index >= len(script):
            return ToolSelection(finish=True, rationale="done")
        selection = script[self.index]
        self.index += 1
        return selection


class MockStoreModel(ModelClient):
    provider = "openrouter-test"

    def __init__(self) -> None:
        self.index = 0

    async def select_tool(self, state, tools):
        script = [
            ("memory_eval.mark_phase", {"phase": "inspect"}, "start inspect"),
            ("fs.list_dir", {"path": "."}, "list files"),
            ("code.detect_language", {"path": "."}, "detect language"),
            ("code.detect_package_manager", {"path": "."}, "detect package manager"),
            ("code.find_tests", {"path": "."}, "find tests"),
            ("exec.detect_test_command", {}, "detect pytest"),
            ("memory_eval.mark_phase", {"phase": "reproduce"}, "start reproduce"),
            ("exec.run_tests", {"command": "pytest"}, "reproduce failure"),
            ("memory_eval.mark_phase", {"phase": "diagnose"}, "start diagnose"),
            ("code.extract_failure_locations", {"output": state.last_command_output}, "extract locations"),
            ("subagent.spawn_diagnosis", {"task": "diagnose mock-store pytest failure", "context": {"output": state.last_command_output}}, "diagnose"),
            ("memory_eval.record_observation", {"text": "pricing discount failure reproduced", "tags": ["diagnosis"]}, "record observation"),
            ("memory_eval.mark_phase", {"phase": "plan_patch"}, "start patch planning"),
            ("code.map_test_to_source", {"path": "tests/test_pricing.py"}, "map pricing test"),
            ("fs.read_file", {"path": "mock_store/pricing.py"}, "read source"),
            ("fs.read_file", {"path": "tests/test_pricing.py"}, "read test"),
            ("fs.apply_patch", {"patch": ""}, "apply validated model patch"),
            ("memory_eval.mark_phase", {"phase": "validate"}, "start validation"),
            ("exec.run_targeted_tests", {"command": "pytest tests/test_pricing.py"}, "targeted tests"),
            ("exec.run_tests", {"command": "pytest"}, "full tests"),
            ("git.diff", {}, "capture diff"),
            ("memory_eval.mark_phase", {"phase": "review"}, "start review"),
            ("subagent.spawn_review", {"task": "review final mock-store patch", "context": {"diff": state.last_text_output}}, "review"),
            ("memory_eval.summarize_context", {"observations": ["model patch applied", "tests passed"], "max_chars": 1000}, "summarize"),
            ("memory_eval.retrieve_artifacts", {"keys": ["patch_plan", "subagents", "phases"]}, "retrieve"),
            ("memory_eval.mark_phase", {"phase": "report"}, "start report"),
            ("exec.command_history", {}, "commands"),
            ("memory_eval.export_session", {}, "export"),
        ]
        if self.index >= len(script):
            return ToolSelection(finish=True, rationale="done")
        tool_name, arguments, rationale = script[self.index]
        self.index += 1
        return ToolSelection(tool_name=tool_name, arguments=arguments, rationale=rationale)

    async def complete_json(self, *, prompt, schema_name, json_schema):
        patch = (
            "diff --git a/mock_store/pricing.py b/mock_store/pricing.py\n"
            "--- a/mock_store/pricing.py\n"
            "+++ b/mock_store/pricing.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def apply_discount(price: float, percent: float) -> float:\n"
            "-    return price - percent\n"
            "+    return price * (1 - percent / 100)\n"
        )
        if schema_name == "DiagnosisResult":
            return ModelJsonResponse(
                data={
                    "root_cause": "apply_discount subtracts the percent value directly instead of applying it as a percentage",
                    "evidence": {
                        "test": "test expected apply_discount(200, 20) == 160",
                        "source": "source returns price - percent",
                    },
                    "implicated_files": ["mock_store/pricing.py"],
                    "recommended_patch_direction": "Change calculation to price * (1 - percent / 100)",
                    "confidence": 0.92,
                    "risks": [],
                }
            )
        if schema_name == "PatchPlan":
            return ModelJsonResponse(
                data={
                    "task_classification": "source_fix",
                    "root_cause": "apply_discount subtracts percent points from price instead of computing a percentage discount",
                    "evidence_refs": ["tests/test_pricing.py", "mock_store/pricing.py"],
                    "planned_changed_files": ["mock_store/pricing.py"],
                    "edits": [
                        {
                            "path": "mock_store/pricing.py",
                            "before": "return price - percent",
                            "after": "return price * (1 - percent / 100)",
                        }
                    ],
                    "patch": patch,
                    "risk_notes": ["Limited to pricing calculation source file."],
                    "validation_expectations": ["pytest tests/test_pricing.py", "pytest"],
                    "summary": "Apply percentage discount formula.",
                }
            )
        if schema_name == "ReviewResult":
            return ModelJsonResponse(
                data={
                    "approved": True,
                    "issues": [],
                    "evidence": {"diff": "mock_store/pricing.py changed", "tests": "targeted and full pytest passed"},
                    "regression_risk": "low",
                    "missing_validation": [],
                    "confidence": 0.9,
                }
            )
        raise AssertionError(f"unexpected schema: {schema_name}")


class EarlyFinishMockStoreModel(MockStoreModel):
    async def select_tool(self, state, tools):
        script = [
            ("fs.list_dir", {"path": "."}, "list files"),
            ("code.detect_language", {"path": "."}, "detect language"),
            ("code.detect_package_manager", {"path": "."}, "detect package manager"),
        ]
        if self.index < len(script):
            tool_name, arguments, rationale = script[self.index]
            self.index += 1
            return ToolSelection(tool_name=tool_name, arguments=arguments, rationale=rationale)
        self.index += 1
        return ToolSelection(finish=True, rationale="premature finish")


class PrematurePatchValidationModel(MockStoreModel):
    async def select_tool(self, state, tools):
        script = [
            ("memory_eval.mark_phase", {"phase": "reproduce"}, "start reproduce"),
            ("exec.run_tests", {"command": "pytest"}, "reproduce failure"),
            ("memory_eval.mark_phase", {"phase": "diagnose"}, "start diagnose"),
            ("code.extract_failure_locations", {"output": state.last_command_output}, "extract locations"),
            ("subagent.spawn_diagnosis", {"task": "diagnose mock-store pytest failure", "context": {"output": state.last_command_output}}, "diagnose"),
            ("memory_eval.record_observation", {"text": "pricing discount failure reproduced", "tags": ["diagnosis"]}, "record observation"),
            ("memory_eval.mark_phase", {"phase": "plan_patch"}, "start patch planning"),
            ("fs.read_file", {"path": "mock_store/pricing.py"}, "read source"),
            (
                "code.validate_patch_shape",
                {
                    "task_classification": "bug_fix",
                    "target_files": ["mock_store/pricing.py"],
                    "patch": {"mock_store/pricing.py": "not a unified diff"},
                },
                "premature validation",
            ),
        ]
        if self.index >= len(script):
            return ToolSelection(finish=True, rationale="done")
        tool_name, arguments, rationale = script[self.index]
        self.index += 1
        return ToolSelection(tool_name=tool_name, arguments=arguments, rationale=rationale)


def test_fixture_repair_produces_success_report(tmp_path: Path) -> None:
    source = Path(__file__).parents[2] / "fixtures" / "buggy-python-repo"
    repo = tmp_path / "repo"
    shutil.copytree(source, repo, ignore=COPY_IGNORE)
    config = PatchPilotConfig(repo=repo, trace_dir=tmp_path / "traces", allow_write=True, allow_exec=True)

    report = asyncio.run(RepairRuntime(config, FakeModelClient()).run("repair failing pytest", "pytest"))

    assert report.status == "success"
    assert report.trace_id
    assert report.report_path
    assert json.loads(Path(report.report_path).read_text(encoding="utf-8"))["report_path"] == report.report_path
    assert report.subagents
    assert (repo / "buggy_math" / "calculator.py").read_text(encoding="utf-8").strip().endswith("return a + b")


def test_generic_command_report_includes_non_pytest_validation(tmp_path: Path) -> None:
    source = Path(__file__).parents[2] / "fixtures" / "generic-command-repo"
    repo = tmp_path / "repo"
    shutil.copytree(source, repo, ignore=COPY_IGNORE)
    command = f'"{sys.executable}" check.py'
    config = PatchPilotConfig(repo=repo, trace_dir=tmp_path / "traces", allow_exec=True)

    report = asyncio.run(RepairRuntime(config, CommandOnlyModel(command)).run("run supplied command", command))

    assert report.status == "success"
    assert report.tests_run
    assert report.tests_run[-1].command == command
    assert report.tests_run[-1].status == "passed"


def test_mock_store_repair_uses_non_fake_model_contract(tmp_path: Path) -> None:
    source = Path(__file__).parents[2] / "fixtures" / "mock-store-python"
    repo = tmp_path / "repo"
    shutil.copytree(source, repo, ignore=COPY_IGNORE)
    config = PatchPilotConfig(repo=repo, trace_dir=tmp_path / "traces", allow_write=True, allow_exec=True)

    report = asyncio.run(RepairRuntime(config, MockStoreModel()).run("Fix the failing pytest test", "pytest"))

    assert report.status == "success"
    assert report.model_provider == "openrouter-test"
    assert report.tool_calls >= 20
    assert [item.path.as_posix() for item in report.changed_files] == ["mock_store/pricing.py"]
    assert "percentage" in report.root_cause
    assert "price * (1 - percent / 100)" in (repo / "mock_store" / "pricing.py").read_text(encoding="utf-8")
    assert "calculator" not in report.subagents[0]["result"]["root_cause"]


def test_mock_store_repair_recovers_from_premature_model_finish(tmp_path: Path) -> None:
    source = Path(__file__).parents[2] / "fixtures" / "mock-store-python"
    repo = tmp_path / "repo"
    shutil.copytree(source, repo, ignore=COPY_IGNORE)
    config = PatchPilotConfig(repo=repo, trace_dir=tmp_path / "traces", allow_write=True, allow_exec=True)
    runtime = RepairRuntime(config, EarlyFinishMockStoreModel())

    report = asyncio.run(runtime.run("Fix the failing pytest test", "pytest"))
    events = runtime.trace_store.read(report.trace_id)

    assert report.status == "success"
    assert report.tool_calls >= 20
    assert any(event.event_type == "runtime.scaffolded_tool_selection" for event in events)
    assert any(event.event_type == "model.patch_plan" for event in events)
    assert [item.path.as_posix() for item in report.changed_files] == ["mock_store/pricing.py"]


def test_mock_store_repair_rejects_premature_patch_validation(tmp_path: Path) -> None:
    source = Path(__file__).parents[2] / "fixtures" / "mock-store-python"
    repo = tmp_path / "repo"
    shutil.copytree(source, repo, ignore=COPY_IGNORE)
    config = PatchPilotConfig(repo=repo, trace_dir=tmp_path / "traces", allow_write=True, allow_exec=True)
    runtime = RepairRuntime(config, PrematurePatchValidationModel())

    report = asyncio.run(runtime.run("Fix the failing pytest test", "pytest"))
    events = runtime.trace_store.read(report.trace_id)

    assert report.status == "success"
    assert any(event.event_type == "model.patch_plan" for event in events)
    assert not any(
        event.event_type == "tool.completed"
        and event.name == "code.validate_patch_shape"
        and event.status == "failed"
        for event in events
    )
