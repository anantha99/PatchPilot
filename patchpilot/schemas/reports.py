"""Report and runtime state schemas."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

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
    command: str
    exit_code: int
    status: Literal["passed", "failed"]


class RepairAttemptReport(BaseModel):
    attempt: int
    result: Literal["passed", "failed"]
    summary: str


class FinalReport(BaseModel):
    goal: str
    status: Literal["success", "partial", "failed"]
    task_classification: str
    root_cause: str
    patch_plan: dict[str, str]
    changed_files: list[ChangedFileReport]
    attempts: list[RepairAttemptReport]
    tests_run: list[TestRunReport]
    subagents: list[dict[str, str]]
    risks: list[str]
    trace_id: str

