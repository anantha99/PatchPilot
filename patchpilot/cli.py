"""PatchPilot command line interface."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from patchpilot.config import PatchPilotConfig
from patchpilot.evals.suites import run_suite
from patchpilot.models.fake import FakeModelClient
from patchpilot.observability.tracing import TraceStore
from patchpilot.runtime.graph import RepairRuntime
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
    trace_dir: Path | None = typer.Option(None, "--trace-dir"),
) -> None:
    config = PatchPilotConfig.from_env(
        repo=repo,
        allow_write=allow_write,
        allow_exec=allow_exec,
        allow_high_risk_exec=allow_high_risk_exec,
        trace_dir=trace_dir or repo / ".patchpilot" / "traces",
    )
    report = asyncio.run(RepairRuntime(config, FakeModelClient()).run(goal, test_command))
    typer.echo(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))


@tools_app.command("list")
def list_tools() -> None:
    registry = build_registry()
    rows = []
    for spec in registry.list():
        rows.append(
            {
                "name": spec.name,
                "namespace": spec.namespace.value,
                "description": spec.description,
                "permission": spec.permission.value,
                "input_schema": spec.input_schema.__name__,
                "output_schema": spec.output_schema.__name__,
                "retry_policy": spec.retry_policy.model_dump(),
                "rate_limit": spec.rate_limit.model_dump(),
            }
        )
    typer.echo(json.dumps(rows, indent=2, sort_keys=True))


@trace_app.command("show")
def show_trace(trace_id: str, trace_dir: Path = typer.Option(Path(".patchpilot/traces"), "--trace-dir")) -> None:
    events = TraceStore(trace_dir).read(trace_id)
    typer.echo(json.dumps([event.model_dump(mode="json") for event in events], indent=2, sort_keys=True))


@app.command()
def eval(
    suite: str = typer.Option("smoke", "--suite"),
    repo: Path = typer.Option(Path("fixtures/buggy-python-repo"), "--repo"),
) -> None:
    result = asyncio.run(run_suite(suite, repo))
    typer.echo(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
