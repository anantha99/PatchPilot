"""Typed runtime state shared across phases, retries, and reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceLink(BaseModel):
    source: str
    path: Path | None = None
    summary: str = ""


class WorkingSetArtifact(BaseModel):
    relevant_tests: list[Path] = Field(default_factory=list)
    implicated_sources: list[Path] = Field(default_factory=list)
    source_candidates: dict[str, list[Path]] = Field(default_factory=dict)
    evidence_links: list[EvidenceLink] = Field(default_factory=list)
    unresolved_unknowns: list[str] = Field(default_factory=list)
    summaries: dict[str, str] = Field(default_factory=dict)


class RepairAttemptArtifact(BaseModel):
    attempt: int
    status: Literal["planned", "applied", "passed", "failed", "rejected", "budget_exhausted"]
    patch_plan: dict[str, Any] = Field(default_factory=dict)
    semantic_validation: dict[str, Any] = Field(default_factory=dict)
    apply_result: dict[str, Any] = Field(default_factory=dict)
    targeted_test: dict[str, Any] = Field(default_factory=dict)
    full_test: dict[str, Any] = Field(default_factory=dict)
    diff_summary: str = ""
    review_output: dict[str, Any] = Field(default_factory=dict)
    changed_files: list[Path] = Field(default_factory=list)
    failure_category: str | None = None
    retry_rationale: str | None = None


class SessionState(BaseModel):
    model_config = {"protected_namespaces": ()}

    repo: Path
    goal: str
    test_command: str | None = None
    phase: str = "inspect"
    tool_history: list[dict[str, Any]] = Field(default_factory=list)
    model_calls: int = 0
    last_output: dict[str, Any] = Field(default_factory=dict)
    last_command_output: str = ""
    last_text_output: str = ""
    trace_id: str = ""
    session_id: str = ""
    attempt: int = 1
    validation_status: str = "not_run"
    previous_patch_failures: list[dict[str, Any]] = Field(default_factory=list)
    termination_reason: str | None = None
    model_metadata: list[dict[str, Any]] = Field(default_factory=list)
    working_set: WorkingSetArtifact = Field(default_factory=WorkingSetArtifact)
    attempts: list[RepairAttemptArtifact] = Field(default_factory=list)
    rejected_patch_plans: list[dict[str, Any]] = Field(default_factory=list)

    def record_tool(self, tool_name: str, output: Any) -> None:
        data = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
        self.last_output = data
        if isinstance(data, dict):
            self.last_command_output = "\n".join(str(data.get(key, "")) for key in ("stdout", "stderr"))
            self.last_text_output = str(data.get("stdout") or data.get("text") or data)
            if tool_name in {"exec.run_tests", "exec.run_targeted_tests"}:
                self.validation_status = "passed" if data.get("exit_code") == 0 else "failed"
        self.tool_history.append({"tool_name": tool_name, "output": data})
