"""JSONL trace storage."""

from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4

from patchpilot.schemas.reports import TraceEvent


def new_trace_id() -> str:
    return f"tr_{uuid4().hex[:12]}"


def new_session_id() -> str:
    return f"sess_{uuid4().hex[:12]}"


class TraceStore:
    def __init__(self, trace_dir: Path) -> None:
        self.trace_dir = trace_dir
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    async def record(
        self,
        *,
        trace_id: str,
        session_id: str,
        event_type: str,
        name: str,
        status: str = "success",
        payload: dict | None = None,
        duration_ms: int = 0,
    ) -> None:
        event = TraceEvent(
            trace_id=trace_id,
            session_id=session_id,
            event_type=event_type,
            name=name,
            duration_ms=duration_ms,
            status=status,
            payload=_sanitize_payload({"ts": time.time(), **(payload or {})}),
        )
        path = self.trace_dir / f"{trace_id}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n")

    def read(self, trace_id: str) -> list[TraceEvent]:
        path = self.trace_dir / f"{trace_id}.jsonl"
        if not path.exists():
            return []
        return [
            TraceEvent.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def _sanitize_payload(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if (
                "api_key" in key_text
                or "secret" in key_text
                or key_text == "authorization"
                or key_text.endswith("_access_token")
                or key_text.endswith("_refresh_token")
                or key_text.endswith("_bearer_token")
            ):
                sanitized[key] = "[redacted]"
            else:
                sanitized[key] = _sanitize_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, str) and any(marker in value.lower() for marker in ("openrouter_api_key=", "authorization: bearer", "sk-")):
        return "[redacted]"
    return value
