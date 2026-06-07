"""PatchPilot CLI for repair runs, evals, tool listing, and trace inspection."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

import typer

from patchpilot.config import PatchPilotConfig
from patchpilot.evals.suites import run_suite
from patchpilot.models.openrouter import OpenRouterModelClient
from patchpilot.observability.tracing import TraceStore
from patchpilot.runtime.graph import RepairRuntime
from patchpilot.schemas.tool_io import ToolListItem, ToolsListOutput
from patchpilot.tools import build_registry

app = typer.Typer(help="PatchPilot autonomous failing-test repair agent.")
tools_app = typer.Typer(help="Inspect registered tools.")
trace_app = typer.Typer(help="Inspect trace output.")
app.add_typer(tools_app, name="tools")
app.add_typer(trace_app, name="trace")


@app.command()
def run(
    repo: Path = typer.Option(..., "--repo"),
    goal: str = typer.Option(..., "--goal"),
    test_command: str | None = typer.Option(None, "--test-command"),
    allow_write: bool = typer.Option(False, "--allow-write"),
    allow_exec: bool = typer.Option(False, "--allow-exec"),
    allow_high_risk_exec: bool = typer.Option(False, "--allow-high-risk-exec"),
    model_provider: Literal["openrouter"] = typer.Option("openrouter", "--model-provider"),
    model_profile: str | None = typer.Option(None, "--model-profile"),
    model: str | None = typer.Option(None, "--model"),
    base_url: str | None = typer.Option(None, "--base-url"),
    max_model_calls: int | None = typer.Option(None, "--max-model-calls"),
    prompt_cache: bool = typer.Option(True, "--prompt-cache/--no-prompt-cache"),
    trace_dir: Path | None = typer.Option(None, "--trace-dir"),
) -> None:
    """Run one repair session and print the persisted final report JSON."""
    config = PatchPilotConfig.from_env(
        repo=repo,
        model_provider=model_provider,
        **({"model_profile": model_profile} if model_profile else {}),
        **({"model": model} if model else {}),
        **({"base_url": base_url} if base_url else {}),
        **({"max_model_calls": max_model_calls} if max_model_calls is not None else {}),
        enable_prompt_cache=prompt_cache,
        allow_write=allow_write,
        allow_exec=allow_exec,
        allow_high_risk_exec=allow_high_risk_exec,
        trace_dir=trace_dir or repo / ".patchpilot" / "traces",
    )
    model = OpenRouterModelClient(config)
    report = asyncio.run(RepairRuntime(config, model).run(goal, test_command))
    typer.echo(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))


@tools_app.command("list")
def list_tools() -> None:
    registry = build_registry()
    output = ToolsListOutput(tools=[ToolListItem.model_validate(spec.metadata()) for spec in registry.list()])
    typer.echo(json.dumps(output.model_dump(mode="json"), indent=2, sort_keys=True))


@trace_app.command("show")
def show_trace(trace_id: str, trace_dir: Path = typer.Option(Path(".patchpilot/traces"), "--trace-dir")) -> None:
    events = TraceStore(trace_dir).read(trace_id)
    typer.echo(json.dumps([event.model_dump(mode="json") for event in events], indent=2, sort_keys=True))


@app.command()
def eval(
    suite: str = typer.Option("smoke", "--suite"),
    repo: Path = typer.Option(Path("fixtures/mock-store-python"), "--repo"),
    model_provider: Literal["openrouter"] = typer.Option("openrouter", "--model-provider"),
    model_profile: str | None = typer.Option(None, "--model-profile"),
    model: str | None = typer.Option(None, "--model"),
    live_eval: bool = typer.Option(False, "--live-eval"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Run a named eval suite; live runs keep progress on stderr."""
    try:
        progress = None if quiet or not live_eval else _print_progress
        result = asyncio.run(run_suite(suite, repo, model_provider=model_provider, model_profile=model_profile, model=model, live_eval=live_eval, progress=progress))
    except ValueError as exc:
        typer.echo(json.dumps({"error": {"type": "unknown_eval_suite", "message": str(exc)}}, indent=2, sort_keys=True))
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result, indent=2, sort_keys=True))


def _print_progress(payload: dict) -> None:
    event = payload.get("event", "progress")
    fixture = payload.get("fixture")
    phase = payload.get("phase")
    elapsed = payload.get("elapsed_seconds")
    fields = []
    if fixture:
        fields.append(f"fixture={fixture}")
    if phase:
        fields.append(f"phase={phase}")
    if payload.get("trace_id"):
        fields.append(f"trace={payload['trace_id']}")
    if payload.get("report_path"):
        fields.append(f"report={payload['report_path']}")
    if payload.get("markdown_report_path"):
        fields.append(f"markdown_report={payload['markdown_report_path']}")
    if payload.get("model_calls") is not None:
        fields.append(f"model_calls={payload['model_calls']}")
    if payload.get("tool_calls") is not None:
        fields.append(f"tool_calls={payload['tool_calls']}")
    if payload.get("retry_count") is not None:
        fields.append(f"retries={payload['retry_count']}")
    if payload.get("status"):
        fields.append(f"status={payload['status']}")
    if payload.get("failure_category"):
        fields.append(f"failure={payload['failure_category']}")
    if elapsed is not None:
        fields.append(f"elapsed={elapsed}s")
    typer.echo(f"[patchpilot:{event}] " + " ".join(fields), err=True)


if __name__ == "__main__":
    app()
