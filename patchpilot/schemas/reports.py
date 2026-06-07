"""Report and runtime state schemas."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field


class TraceEvent(BaseModel):
    trace_id: str
    session_id: str
    event_type: str
    name: str
    duration_ms: int = 0
    status: str = "success"
    payload: dict[str, Any] = Field(default_factory=dict)


class ChangedFileReport(BaseModel):
    path: Path
    change_type: str
    justification: str


class TestRunReport(BaseModel):
    __test__: ClassVar[bool] = False

    command: str
    exit_code: int
    status: Literal["passed", "failed"]


class RepairAttemptReport(BaseModel):
    attempt: int
    result: Literal["passed", "failed", "rejected", "budget_exhausted"]
    summary: str
    changed_files: list[Path] = Field(default_factory=list)
    semantic_validation: dict[str, Any] = Field(default_factory=dict)
    targeted_test: dict[str, Any] = Field(default_factory=dict)
    full_test: dict[str, Any] = Field(default_factory=dict)
    failure_category: str | None = None
    retry_rationale: str | None = None


class FinalReport(BaseModel):
    goal: str
    status: Literal["success", "partial", "failed"]
    task_classification: str
    root_cause: str
    patch_plan: dict[str, Any]
    changed_files: list[ChangedFileReport]
    attempts: list[RepairAttemptReport]
    tests_run: list[TestRunReport]
    subagents: list[dict[str, Any]]
    risks: list[str]
    trace_id: str
    tool_calls: int = 0
    model_provider: str | None = None
    model: str | None = None
    model_usage_summary: dict[str, Any] = Field(default_factory=dict)
    estimated_cost: float | None = None
    cache_summary: dict[str, Any] = Field(default_factory=dict)
    semantic_validation: list[dict[str, Any]] = Field(default_factory=list)
    rejected_patch_plans: list[dict[str, Any]] = Field(default_factory=list)
    retry_summary: dict[str, Any] = Field(default_factory=dict)
    review_result: dict[str, Any] = Field(default_factory=dict)
    trace_path: str | None = None
    report_path: str | None = None
    failure_reason: str | None = None
