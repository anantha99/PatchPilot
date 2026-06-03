"""Command execution tools with explicit risk policy."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from patchpilot.schemas.common import CommandRisk, EmptyInput, Permission, ToolNamespace
from patchpilot.schemas.tool_io import (
    CommandExistsInput,
    CommandExistsOutput,
    CommandHistoryOutput,
    CommandOutput,
    CommandRiskInput,
    CommandRiskOutput,
    DetectedCommandOutput,
    EnvOutput,
    RunCommandInput,
    TestCommandInput,
    TimeoutProbeInput,
)
from patchpilot.tools.helpers import classify_command_risk, detect_test_command, run_process
from patchpilot.tools.registry import ToolContext, ToolRegistry


async def _run(input: RunCommandInput, context: ToolContext) -> CommandOutput:
    command = _normalize_command(input.command)
    risk = classify_command_risk(command)
    if input.risk != CommandRisk.LOW:
        risk = input.risk
    output = await run_process(
        Path(context.repo_root),
        command,
        input.timeout_seconds or context.config.command_timeout_seconds,
        risk,
        allow_high_risk=context.config.allow_high_risk_exec,
    )
    context.command_history.append(output)
    return output


def _normalize_command(command: str) -> str:
    if command == "pytest":
        return f'"{sys.executable}" -m pytest'
    if command.startswith("pytest "):
        return f'"{sys.executable}" -m pytest {command.removeprefix("pytest ")}'
    return command


def register(registry: ToolRegistry) -> None:
    @registry.tool(
        name="exec.run_command",
        namespace=ToolNamespace.EXEC,
        description="Run a bounded shell command in the repository.",
        input_schema=RunCommandInput,
        output_schema=CommandOutput,
        permission=Permission.EXEC,
    )
    async def run_command(input: RunCommandInput, context: ToolContext) -> CommandOutput:
        return await _run(input, context)

    @registry.tool(
        name="exec.run_tests",
        namespace=ToolNamespace.EXEC,
        description="Run the detected or supplied test command.",
        input_schema=TestCommandInput,
        output_schema=CommandOutput,
        permission=Permission.EXEC,
    )
    async def run_tests(input: TestCommandInput, context: ToolContext) -> CommandOutput:
        command = input.command or detect_test_command(Path(context.repo_root)) or "pytest"
        return await _run(RunCommandInput(command=command), context)

    @registry.tool(
        name="exec.run_targeted_tests",
        namespace=ToolNamespace.EXEC,
        description="Run a targeted test command or target.",
        input_schema=TestCommandInput,
        output_schema=CommandOutput,
        permission=Permission.EXEC,
    )
    async def run_targeted_tests(input: TestCommandInput, context: ToolContext) -> CommandOutput:
        if input.command:
            command = input.command
        elif input.target:
            command = f"pytest {input.target}"
        else:
            command = "pytest"
        return await _run(RunCommandInput(command=command), context)

    @registry.tool(
        name="exec.detect_test_command",
        namespace=ToolNamespace.EXEC,
        description="Detect a likely repository test command.",
        input_schema=EmptyInput,
        output_schema=DetectedCommandOutput,
        permission=Permission.READ,
    )
    async def detect_tests(input: EmptyInput, context: ToolContext) -> DetectedCommandOutput:
        return DetectedCommandOutput(command=detect_test_command(Path(context.repo_root)))

    @registry.tool(
        name="exec.command_exists",
        namespace=ToolNamespace.EXEC,
        description="Check whether a command is available on PATH.",
        input_schema=CommandExistsInput,
        output_schema=CommandExistsOutput,
        permission=Permission.READ,
    )
    async def command_exists(input: CommandExistsInput, context: ToolContext) -> CommandExistsOutput:
        return CommandExistsOutput(exists=shutil.which(input.command) is not None)

    @registry.tool(
        name="exec.command_history",
        namespace=ToolNamespace.EXEC,
        description="Return commands run in this tool context.",
        input_schema=EmptyInput,
        output_schema=CommandHistoryOutput,
        permission=Permission.READ,
    )
    async def command_history(input: EmptyInput, context: ToolContext) -> CommandHistoryOutput:
        return CommandHistoryOutput(commands=context.command_history)

    @registry.tool(
        name="exec.capture_environment",
        namespace=ToolNamespace.EXEC,
        description="Capture a small allowlist of environment values.",
        input_schema=EmptyInput,
        output_schema=EnvOutput,
        permission=Permission.READ,
    )
    async def capture_environment(input: EmptyInput, context: ToolContext) -> EnvOutput:
        keys = ["PYTHONPATH", "VIRTUAL_ENV", "PATH"]
        return EnvOutput(values={key: os.environ.get(key, "") for key in keys})

    @registry.tool(
        name="exec.classify_command_risk",
        namespace=ToolNamespace.EXEC,
        description="Classify a shell command risk before execution.",
        input_schema=CommandRiskInput,
        output_schema=CommandRiskOutput,
        permission=Permission.READ,
    )
    async def classify_risk(input: CommandRiskInput, context: ToolContext) -> CommandRiskOutput:
        return CommandRiskOutput(risk=classify_command_risk(input.command))

    @registry.tool(
        name="exec.probe_timeout",
        namespace=ToolNamespace.EXEC,
        description="Run a command with a short timeout to probe runtime behavior.",
        input_schema=TimeoutProbeInput,
        output_schema=CommandOutput,
        permission=Permission.EXEC,
    )
    async def probe_timeout(input: TimeoutProbeInput, context: ToolContext) -> CommandOutput:
        return await _run(
            RunCommandInput(command=input.command, timeout_seconds=input.timeout_seconds),
            context,
        )

    for name, command in {
        "exec.run_formatter": "python -m black --check .",
        "exec.run_linter": "python -m ruff check .",
        "exec.run_typecheck": "python -m mypy .",
    }.items():
        async def optional_tool(input: EmptyInput, context: ToolContext, command: str = command) -> CommandOutput:
            executable = command.split()[2] if command.startswith("python -m ") else command.split()[0]
            if executable in {"black", "ruff", "mypy"} and shutil.which(executable) is None:
                return CommandOutput(command=command, stdout="", stderr=f"{executable} is unavailable", exit_code=127, duration_ms=0, risk=CommandRisk.LOW)
            return await _run(RunCommandInput(command=command), context)

        registry.tool(
            name=name,
            namespace=ToolNamespace.EXEC,
            description=f"Run optional quality command {command}.",
            input_schema=EmptyInput,
            output_schema=CommandOutput,
            permission=Permission.EXEC,
        )(optional_tool)
