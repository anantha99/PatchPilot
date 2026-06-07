"""Tool input and output schemas."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from patchpilot.schemas.common import CommandRisk


class ListDirInput(BaseModel):
    path: Path = Path(".")


class ListDirOutput(BaseModel):
    entries: list[str]


class ReadFileInput(BaseModel):
    path: Path
    max_bytes: int | None = None


class ReadFilesInput(BaseModel):
    paths: list[Path]
    max_bytes_per_file: int | None = None


class WriteFileInput(BaseModel):
    path: Path
    content: str


class ApplyPatchInput(BaseModel):
    patch: str = ""
    structured_edits: list[dict[str, Any]] = Field(default_factory=list)


class ApplyPatchOutput(BaseModel):
    applied: bool
    stdout: str = ""
    stderr: str = ""
    changed_files: list[Path] = Field(default_factory=list)
    hunks_applied: int = 0
    clean_diff: str = ""
    summary: str = ""


class FileExistsOutput(BaseModel):
    exists: bool


class StatFileOutput(BaseModel):
    exists: bool
    size: int | None = None
    modified_time: float | None = None


class GlobInput(BaseModel):
    pattern: str


class GlobOutput(BaseModel):
    paths: list[Path]


class HashFileOutput(BaseModel):
    sha256: str


class TempFileInput(BaseModel):
    prefix: str = "patchpilot-"
    suffix: str = ""
    content: str = ""


class TempFileOutput(BaseModel):
    path: Path


class GitCommandOutput(BaseModel):
    stdout: str
    stderr: str
    exit_code: int


class DiffFileInput(BaseModel):
    path: Path


class GitLogInput(BaseModel):
    limit: int = 10


class GitShowInput(BaseModel):
    revision: str


class GitBlameInput(BaseModel):
    path: Path


class SearchTextInput(BaseModel):
    query: str
    path: Path = Path(".")
    max_results: int = 50


class SearchRegexInput(BaseModel):
    pattern: str
    path: Path = Path(".")
    max_results: int = 50


class DetectLanguageOutput(BaseModel):
    languages: dict[str, int]
    primary_language: str | None = None


class DetectPackageManagerOutput(BaseModel):
    managers: list[str]


class FindTestsOutput(BaseModel):
    test_files: list[Path]


class ParseImportsInput(BaseModel):
    path: Path


class ParseImportsOutput(BaseModel):
    imports: list[str]


class FailureLocationsInput(BaseModel):
    output: str


class FailureLocationsOutput(BaseModel):
    locations: list[str]


class PatchValidationInput(BaseModel):
    task_classification: str
    target_files: list[Path]
    patch: str | None = None
    structured_edits: list["PatchEdit"] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    root_cause: str = ""
    patch_plan: dict[str, Any] = Field(default_factory=dict)
    max_diff_lines: int = 200
    protected_paths: list[Path] = Field(default_factory=lambda: [Path(".git"), Path(".env")])
    allow_test_only: bool = False


class PatchValidationOutput(BaseModel):
    valid: bool
    reasons: list[str] = Field(default_factory=list)
    target_files: list[Path] = Field(default_factory=list)
    changed_files: list[Path] = Field(default_factory=list)
    diff_lines: int = 0
    semantic_reasons: list[str] = Field(default_factory=list)


class PatchEdit(BaseModel):
    path: Path
    before: str
    after: str
    evidence_refs: list[str] = Field(default_factory=list)
    purpose: str = ""
    expected_validation: list[str] = Field(default_factory=list)
    root_cause_linkage: str = ""


class PatchPlan(BaseModel):
    task_classification: str
    root_cause: str
    evidence_refs: list[str] = Field(default_factory=list)
    planned_changed_files: list[Path] = Field(default_factory=list)
    edits: list[PatchEdit]
    patch: str = ""
    unified_diff: str | None = None
    risk_notes: list[str] = Field(default_factory=list)
    validation_expectations: list[str] = Field(default_factory=list)
    summary: str


class PatchApplyResult(BaseModel):
    changed_files: list[Path]
    summary: str


class SummarizeFilesInput(BaseModel):
    paths: list[Path]
    max_chars_per_file: int = 1200


class RunCommandInput(BaseModel):
    command: str
    timeout_seconds: int | None = None
    risk: CommandRisk = CommandRisk.LOW


class CommandOutput(BaseModel):
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    risk: CommandRisk


class TestCommandInput(BaseModel):
    command: str | None = None
    target: str | None = None


class EnvOutput(BaseModel):
    values: dict[str, str]


class CommandExistsInput(BaseModel):
    command: str


class CommandExistsOutput(BaseModel):
    exists: bool


class CommandHistoryOutput(BaseModel):
    commands: list[CommandOutput]


class DetectedCommandOutput(BaseModel):
    command: str | None = None


class CommandRiskInput(BaseModel):
    command: str


class CommandRiskOutput(BaseModel):
    risk: CommandRisk


class TimeoutProbeInput(BaseModel):
    command: str
    timeout_seconds: int = 5


class ObservationInput(BaseModel):
    text: str
    tags: list[str] = Field(default_factory=list)


class ObservationOutput(BaseModel):
    observation_id: str


class ContextSummaryInput(BaseModel):
    observations: list[str]
    max_chars: int = 2000


class ContextSummaryOutput(BaseModel):
    summary: str


class RetrieveArtifactsInput(BaseModel):
    keys: list[str] | None = None


class ArtifactsOutput(BaseModel):
    artifacts: dict[str, Any]


class DecisionInput(BaseModel):
    decision: str
    reason: str


class DecisionOutput(BaseModel):
    decision_id: str


class ArtifactInput(BaseModel):
    key: str
    value: Any


class WriteJsonInput(BaseModel):
    path: Path
    data: dict[str, Any]


class ArtifactKeyInput(BaseModel):
    key: str


class PhaseInput(BaseModel):
    phase: str


class TraceAssertInput(BaseModel):
    trace_id: str
    min_tool_calls: int = 20


class FixtureInput(BaseModel):
    fixture: str = "buggy-python-repo"


class EvalSuiteInput(BaseModel):
    suite: str = "smoke"


class EvalScoreOutput(BaseModel):
    passed: bool
    score: float
    checks: dict[str, bool]


class SubagentTaskInput(BaseModel):
    task: str
    context: dict[str, Any] = Field(default_factory=dict)


class SubagentConfig(BaseModel):
    kind: str
    allowed_tools: list[str]
    max_model_calls: int = 3
    max_tool_calls: int = 5
    context_payload: dict[str, Any] = Field(default_factory=dict)
    output_schema: str


class DiagnosisResult(BaseModel):
    root_cause: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    evidence_links: list[str] = Field(default_factory=list)
    implicated_files: list[Path] = Field(default_factory=list)
    shared_root_cause: str = ""
    recommended_patch_direction: str
    confidence: float = 0.0
    risks: list[str] = Field(default_factory=list)


class ReviewResult(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    regression_risk: str = "unknown"
    missing_validation: list[str] = Field(default_factory=list)
    changed_file_necessity: dict[str, str] = Field(default_factory=dict)
    blocking: bool = False
    confidence: float = 0.0


class SubagentResultOutput(BaseModel):
    name: str
    kind: str
    status: str
    result: dict[str, Any]


class ToolListItem(BaseModel):
    name: str
    namespace: str
    description: str
    permission: str
    input_schema: str
    output_schema: str
    retry_policy: dict[str, Any]
    rate_limit: dict[str, Any]


class ToolsListOutput(BaseModel):
    tools: list[ToolListItem]
