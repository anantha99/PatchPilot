"""Runtime retry tests for failed attempts, revised plans, and final reports."""

from pathlib import Path
import asyncio

from patchpilot.config import PatchPilotConfig
from patchpilot.models.base import ModelClient, ModelJsonResponse, ToolSelection
from patchpilot.runtime.graph import RepairRuntime


class RetryPatchModel(ModelClient):
    provider = "openrouter-test"

    def __init__(self) -> None:
        self.patch_calls = 0

    async def select_tool(self, state, tools):
        return ToolSelection(finish=True, rationale="let runtime scaffold phases")

    async def complete_json(self, *, prompt, schema_name, json_schema):
        if schema_name == "DiagnosisResult":
            return ModelJsonResponse(
                data={
                    "root_cause": "discount calculation treats percent as points instead of a percentage",
                    "evidence": {"test": "pytest output", "source": "pricing.py"},
                    "evidence_links": ["tests/test_pricing.py", "pricing.py"],
                    "implicated_files": ["pricing.py"],
                    "shared_root_cause": "percentage discount contract drift",
                    "recommended_patch_direction": "Use a percentage multiplier",
                    "confidence": 0.9,
                    "risks": [],
                }
            )
        if schema_name == "PatchPlan":
            self.patch_calls += 1
            if self.patch_calls == 1:
                before = "return price - percent"
                after = "return price * percent"
            else:
                before = "return price * percent"
                after = "return price * (1 - percent / 100)"
            patch = (
                "diff --git a/pricing.py b/pricing.py\n"
                "--- a/pricing.py\n"
                "+++ b/pricing.py\n"
                "@@ -1,2 +1,2 @@\n"
                " def apply_discount(price: float, percent: float) -> float:\n"
                f"-    {before}\n"
                f"+    {after}\n"
            )
            return ModelJsonResponse(
                data={
                    "task_classification": "source_fix",
                    "root_cause": "discount calculation treats percent as points instead of a percentage",
                    "evidence_refs": ["tests/test_pricing.py", "pricing.py"],
                    "planned_changed_files": ["pricing.py"],
                    "edits": [
                        {
                            "path": "pricing.py",
                            "before": before,
                            "after": after,
                            "evidence_refs": ["tests/test_pricing.py", "pricing.py"],
                            "purpose": "Repair discount formula",
                            "expected_validation": ["pytest tests/test_pricing.py", "pytest"],
                            "root_cause_linkage": "same discount formula root cause",
                        }
                    ],
                    "patch": patch,
                    "summary": "Repair discount formula.",
                }
            )
        if schema_name == "ReviewResult":
            return ModelJsonResponse(
                data={
                    "approved": True,
                    "issues": [],
                    "evidence": {},
                    "regression_risk": "low",
                    "missing_validation": [],
                    "changed_file_necessity": {"pricing.py": "contains the faulty formula"},
                    "blocking": False,
                    "confidence": 0.9,
                }
            )
        raise AssertionError(schema_name)


class RetryAfterApplyFailureModel(RetryPatchModel):
    async def complete_json(self, *, prompt, schema_name, json_schema):
        if schema_name != "PatchPlan":
            return await super().complete_json(prompt=prompt, schema_name=schema_name, json_schema=json_schema)
        self.patch_calls += 1
        if self.patch_calls == 1:
            before = "return price + percent"
            after = "return price * (1 - percent / 100)"
        else:
            before = "return price - percent"
            after = "return price * (1 - percent / 100)"
        patch = (
            "diff --git a/pricing.py b/pricing.py\n"
            "--- a/pricing.py\n"
            "+++ b/pricing.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def apply_discount(price: float, percent: float) -> float:\n"
            f"-    {before}\n"
            f"+    {after}\n"
        )
        return ModelJsonResponse(
            data={
                "task_classification": "source_fix",
                "root_cause": "discount calculation treats percent as points instead of a percentage",
                "evidence_refs": ["tests/test_pricing.py", "pricing.py"],
                "planned_changed_files": ["pricing.py"],
                "edits": [
                    {
                        "path": "pricing.py",
                        "before": before,
                        "after": after,
                        "evidence_refs": ["tests/test_pricing.py", "pricing.py"],
                        "purpose": "Repair discount formula",
                        "expected_validation": ["pytest tests/test_pricing.py", "pytest"],
                        "root_cause_linkage": "same discount formula root cause",
                    }
                ],
                "patch": patch,
                "summary": "Repair discount formula.",
            }
        )


class SearchReplaceOnlyModel(RetryPatchModel):
    async def complete_json(self, *, prompt, schema_name, json_schema):
        if schema_name != "PatchPlan":
            return await super().complete_json(prompt=prompt, schema_name=schema_name, json_schema=json_schema)
        return ModelJsonResponse(
            data={
                "task_classification": "source_fix",
                "root_cause": "discount calculation treats percent as points instead of a percentage",
                "evidence_refs": ["tests/test_pricing.py", "pricing.py"],
                "planned_changed_files": ["pricing.py"],
                "edits": [
                    {
                        "path": "pricing.py",
                        "before": "return price - percent",
                        "after": "return price * (1 - percent / 100)",
                        "evidence_refs": ["tests/test_pricing.py", "pricing.py"],
                        "purpose": "Repair discount formula",
                        "expected_validation": ["pytest tests/test_pricing.py", "pytest"],
                        "root_cause_linkage": "same discount formula root cause",
                    }
                ],
                "patch": "",
                "summary": "Repair discount formula with structured search/replace.",
            }
        )


class ContractRetryModel(RetryPatchModel):
    async def complete_json(self, *, prompt, schema_name, json_schema):
        if schema_name == "DiagnosisResult":
            return ModelJsonResponse(
                data={
                    "root_cause": "two-file contract drift",
                    "evidence": {"test": "pytest output", "source": "a.py and b.py"},
                    "evidence_links": ["tests/test_contract.py", "a.py", "b.py"],
                    "implicated_files": ["a.py", "b.py"],
                    "shared_root_cause": "two-file contract drift",
                    "recommended_patch_direction": "Update both contract constants",
                    "confidence": 0.9,
                    "risks": [],
                }
            )
        if schema_name != "PatchPlan":
            return await super().complete_json(prompt=prompt, schema_name=schema_name, json_schema=json_schema)
        self.patch_calls += 1
        edits = [
            {
                "path": "a.py",
                "before": "VALUE = 1",
                "after": "VALUE = 2",
                "evidence_refs": ["tests/test_contract.py", "a.py"],
                "purpose": "Update first half of contract",
                "expected_validation": ["pytest tests/test_contract.py", "pytest"],
                "root_cause_linkage": "same two-file contract",
            }
        ]
        expected = ["a.py"]
        if self.patch_calls > 1:
            expected = ["b.py"]
            edits = [
                {
                    "path": "b.py",
                    "before": "LIMIT = 1",
                    "after": "LIMIT = 2",
                    "evidence_refs": ["tests/test_contract.py", "b.py"],
                    "purpose": "Update second half of contract",
                    "expected_validation": ["pytest tests/test_contract.py", "pytest"],
                    "root_cause_linkage": "same two-file contract",
                }
            ]
        return ModelJsonResponse(
            data={
                "task_classification": "source_fix",
                "root_cause": "two-file contract drift",
                "evidence_refs": ["tests/test_contract.py", "a.py", "b.py"],
                "planned_changed_files": expected,
                "edits": edits,
                "patch": "",
                "summary": "Repair two-file contract.",
            }
        )


def test_retry_records_failed_attempt_and_succeeds_on_second_patch(tmp_path: Path) -> None:
    (tmp_path / "pricing.py").write_text(
        "def apply_discount(price: float, percent: float) -> float:\n"
        "    return price - percent\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_pricing.py").write_text(
        "from pricing import apply_discount\n\n"
        "def test_percentage_discount():\n"
        "    assert apply_discount(200, 20) == 160\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n", encoding="utf-8")
    config = PatchPilotConfig(repo=tmp_path, trace_dir=tmp_path / "traces", allow_write=True, allow_exec=True, max_repair_attempts=2)

    report = asyncio.run(RepairRuntime(config, RetryPatchModel()).run("repair discount", "pytest"))

    assert report.status == "success"
    assert len(report.attempts) == 2
    assert report.attempts[0].failure_category == "targeted_tests_failed"
    assert report.attempts[0].retry_rationale
    assert report.attempts[1].result == "passed"
    assert "percent / 100" in (tmp_path / "pricing.py").read_text(encoding="utf-8")


def test_runtime_applies_search_replace_patch_plan_without_model_diff(tmp_path: Path) -> None:
    (tmp_path / "pricing.py").write_text(
        "def apply_discount(price: float, percent: float) -> float:\n"
        "    return price - percent\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_pricing.py").write_text(
        "from pricing import apply_discount\n\n"
        "def test_percentage_discount():\n"
        "    assert apply_discount(200, 20) == 160\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n", encoding="utf-8")
    config = PatchPilotConfig(repo=tmp_path, trace_dir=tmp_path / "traces", allow_write=True, allow_exec=True)

    report = asyncio.run(RepairRuntime(config, SearchReplaceOnlyModel()).run("repair discount", "pytest"))

    assert report.status == "success"
    assert len(report.attempts) == 1
    assert report.attempts[0].result == "passed"
    assert [item.path.as_posix() for item in report.changed_files] == ["pricing.py"]
    assert "percent / 100" in (tmp_path / "pricing.py").read_text(encoding="utf-8")


def test_runtime_retries_blind_partial_multifile_patch_after_tests_fail(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("LIMIT = 1\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_contract.py").write_text(
        "from a import VALUE\n"
        "from b import LIMIT\n\n"
        "def test_two_file_contract():\n"
        "    assert (VALUE, LIMIT) == (2, 2)\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n", encoding="utf-8")
    config = PatchPilotConfig(repo=tmp_path, trace_dir=tmp_path / "traces", allow_write=True, allow_exec=True, max_repair_attempts=2)
    model = ContractRetryModel()

    report = asyncio.run(RepairRuntime(config, model).run("repair two-file contract", "pytest"))

    assert report.status == "success"
    assert model.patch_calls == 2
    assert len(report.attempts) == 2
    assert report.attempts[0].failure_category == "targeted_tests_failed"
    assert report.rejected_patch_plans == []
    assert [item.path.as_posix() for item in report.changed_files] == ["a.py", "b.py"]
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert (tmp_path / "b.py").read_text(encoding="utf-8") == "LIMIT = 2\n"


def test_retry_rejects_missing_search_text_before_apply_and_succeeds_on_second_patch(tmp_path: Path) -> None:
    (tmp_path / "pricing.py").write_text(
        "def apply_discount(price: float, percent: float) -> float:\n"
        "    return price - percent\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_pricing.py").write_text(
        "from pricing import apply_discount\n\n"
        "def test_percentage_discount():\n"
        "    assert apply_discount(200, 20) == 160\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n", encoding="utf-8")
    config = PatchPilotConfig(repo=tmp_path, trace_dir=tmp_path / "traces", allow_write=True, allow_exec=True, max_repair_attempts=2)

    report = asyncio.run(RepairRuntime(config, RetryAfterApplyFailureModel()).run("repair discount", "pytest"))

    assert report.status == "success"
    assert len(report.rejected_patch_plans) == 1
    assert any("structured edit SEARCH text not found" in reason for reason in report.rejected_patch_plans[0]["validation"]["reasons"])
    assert len(report.attempts) == 1
    assert report.attempts[0].result == "passed"
    assert "percent / 100" in (tmp_path / "pricing.py").read_text(encoding="utf-8")
