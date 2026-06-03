"""Repair runtime state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


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

    def record_tool(self, tool_name: str, output: Any) -> None:
        data = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
        self.last_output = data
        if isinstance(data, dict):
            self.last_command_output = "\n".join(str(data.get(key, "")) for key in ("stdout", "stderr"))
            self.last_text_output = str(data.get("stdout") or data.get("text") or data)
        self.tool_history.append({"tool_name": tool_name, "output": data})
