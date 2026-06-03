"""Git tools."""

from __future__ import annotations

from pathlib import Path

from patchpilot.schemas.common import CommandRisk, EmptyInput, Permission, TextOutput, ToolNamespace
from patchpilot.schemas.tool_io import DiffFileInput, GitBlameInput, GitCommandOutput, GitLogInput, GitShowInput
from patchpilot.tools.helpers import run_process
from patchpilot.tools.registry import ToolContext, ToolRegistry


async def _git(context: ToolContext, args: str) -> GitCommandOutput:
    output = await run_process(
        Path(context.repo_root),
        f"git {args}",
        context.config.command_timeout_seconds,
        CommandRisk.LOW,
    )
    return GitCommandOutput(stdout=output.stdout, stderr=output.stderr, exit_code=output.exit_code)


def register(registry: ToolRegistry) -> None:
    @registry.tool(
        name="git.status",
        namespace=ToolNamespace.GIT,
        description="Return git status porcelain output.",
        input_schema=EmptyInput,
        output_schema=GitCommandOutput,
        permission=Permission.READ,
    )
    async def status(input: EmptyInput, context: ToolContext) -> GitCommandOutput:
        return await _git(context, "status --short")

    @registry.tool(
        name="git.diff",
        namespace=ToolNamespace.GIT,
        description="Return current working tree diff.",
        input_schema=EmptyInput,
        output_schema=GitCommandOutput,
        permission=Permission.READ,
    )
    async def diff(input: EmptyInput, context: ToolContext) -> GitCommandOutput:
        return await _git(context, "diff --")

    @registry.tool(
        name="git.diff_file",
        namespace=ToolNamespace.GIT,
        description="Return diff for a single file.",
        input_schema=DiffFileInput,
        output_schema=GitCommandOutput,
        permission=Permission.READ,
    )
    async def diff_file(input: DiffFileInput, context: ToolContext) -> GitCommandOutput:
        return await _git(context, f'diff -- "{input.path}"')

    @registry.tool(
        name="git.log",
        namespace=ToolNamespace.GIT,
        description="Return recent git log entries.",
        input_schema=GitLogInput,
        output_schema=GitCommandOutput,
        permission=Permission.READ,
    )
    async def log(input: GitLogInput, context: ToolContext) -> GitCommandOutput:
        return await _git(context, f"log --oneline -n {input.limit}")

    @registry.tool(
        name="git.show",
        namespace=ToolNamespace.GIT,
        description="Show a git revision.",
        input_schema=GitShowInput,
        output_schema=GitCommandOutput,
        permission=Permission.READ,
    )
    async def show(input: GitShowInput, context: ToolContext) -> GitCommandOutput:
        return await _git(context, f"show --stat --oneline {input.revision}")

    @registry.tool(
        name="git.blame",
        namespace=ToolNamespace.GIT,
        description="Return git blame for a file.",
        input_schema=GitBlameInput,
        output_schema=GitCommandOutput,
        permission=Permission.READ,
    )
    async def blame(input: GitBlameInput, context: ToolContext) -> GitCommandOutput:
        return await _git(context, f'blame -- "{input.path}"')

    @registry.tool(
        name="git.branch",
        namespace=ToolNamespace.GIT,
        description="Return current branch name.",
        input_schema=EmptyInput,
        output_schema=TextOutput,
        permission=Permission.READ,
    )
    async def branch(input: EmptyInput, context: ToolContext) -> TextOutput:
        output = await _git(context, "branch --show-current")
        return TextOutput(text=output.stdout.strip())

    @registry.tool(
        name="git.changed_files",
        namespace=ToolNamespace.GIT,
        description="List changed files.",
        input_schema=EmptyInput,
        output_schema=TextOutput,
        permission=Permission.READ,
    )
    async def changed_files(input: EmptyInput, context: ToolContext) -> TextOutput:
        output = await _git(context, "diff --name-only")
        return TextOutput(text=output.stdout)

    @registry.tool(
        name="git.staged_files",
        namespace=ToolNamespace.GIT,
        description="List staged files.",
        input_schema=EmptyInput,
        output_schema=TextOutput,
        permission=Permission.READ,
    )
    async def staged_files(input: EmptyInput, context: ToolContext) -> TextOutput:
        output = await _git(context, "diff --cached --name-only")
        return TextOutput(text=output.stdout)

    @registry.tool(
        name="git.root",
        namespace=ToolNamespace.GIT,
        description="Return repository root.",
        input_schema=EmptyInput,
        output_schema=TextOutput,
        permission=Permission.READ,
    )
    async def root(input: EmptyInput, context: ToolContext) -> TextOutput:
        output = await _git(context, "rev-parse --show-toplevel")
        return TextOutput(text=output.stdout.strip())

    @registry.tool(
        name="git.merge_base",
        namespace=ToolNamespace.GIT,
        description="Return merge base with HEAD and origin/main when available.",
        input_schema=EmptyInput,
        output_schema=GitCommandOutput,
        permission=Permission.READ,
    )
    async def merge_base(input: EmptyInput, context: ToolContext) -> GitCommandOutput:
        return await _git(context, "merge-base HEAD origin/main")

    @registry.tool(
        name="git.clean_check",
        namespace=ToolNamespace.GIT,
        description="Report whether the working tree is clean.",
        input_schema=EmptyInput,
        output_schema=TextOutput,
        permission=Permission.READ,
    )
    async def clean_check(input: EmptyInput, context: ToolContext) -> TextOutput:
        output = await _git(context, "status --porcelain")
        return TextOutput(text="clean" if output.stdout.strip() == "" else "dirty")

    @registry.tool(
        name="git.summarize_diff",
        namespace=ToolNamespace.GIT,
        description="Return a compact diff stat summary.",
        input_schema=EmptyInput,
        output_schema=GitCommandOutput,
        permission=Permission.READ,
    )
    async def summarize_diff(input: EmptyInput, context: ToolContext) -> GitCommandOutput:
        return await _git(context, "diff --stat")

