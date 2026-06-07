# X-ARC Agent Instructions

<!-- BEGIN COMPOUND CODEX TOOL MAP -->
## Compound Codex Tool Mapping (Claude Compatibility)

This section maps Claude Code plugin tool references to Codex behavior.
Only this block is managed automatically.

Tool mapping:
- Read: use shell reads (cat/sed) or rg
- Write: create files via shell redirection or apply_patch
- Edit/MultiEdit: use apply_patch
- Bash: use shell_command
- Grep: use rg (fallback: grep)
- Glob: use rg --files or find
- LS: use ls via shell_command
- WebFetch/WebSearch: use curl or Context7 for library docs
- AskUserQuestion/Question: present choices as a numbered list in chat and wait for a reply number. For multi-select (multiSelect: true), accept comma-separated numbers. Never skip or auto-configure -- always wait for the user's response before proceeding.
- Task (subagent dispatch) / Subagent / Parallel: run sequentially in main thread; use multi_tool_use.parallel for tool calls
- TaskCreate/TaskUpdate/TaskList/TaskGet/TaskStop/TaskOutput (Claude Code task-tracking, current): use update_plan (Codex's task-tracking primitive)
- TodoWrite/TodoRead (Claude Code task-tracking, legacy -- deprecated, replaced by Task* tools): use update_plan
- Skill: open the referenced SKILL.md and follow it
- ExitPlanMode: ignore
<!-- END COMPOUND CODEX TOOL MAP -->

## Verification Policy

Docker is not the canonical verification path. For normal local verification, use
the project `.venv` directly:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m patchpilot.cli eval --suite smoke --repo fixtures\buggy-python-repo --model-provider fake
```

Use live OpenRouter evaluation only when `.env` is configured and the user
expects network/model cost:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli eval --suite smoke --repo fixtures\mock-store-python --live-eval
.\.venv\Scripts\python.exe -m patchpilot.cli eval --suite v2 --repo fixtures --model-provider openrouter --model-profile v2-strong --live-eval
```

The wrapper script is a convenience path, not the release gate. Use it when the
user explicitly asks for wrapper coverage or when validating the Docker/container
setup itself:

Common targets:

```powershell
.\scripts\xarc-test.ps1 -Target test
.\scripts\xarc-test.ps1 -Target smoke
.\scripts\xarc-test.ps1 -Target live-eval
.\scripts\xarc-test.ps1 -Target shell
```

Direct Docker commands are optional equivalents for container verification only:

```powershell
docker compose run --rm xarc-test
docker compose run --rm xarc-smoke
docker compose run --rm --env-file .env xarc-live-eval
docker compose run --rm xarc-shell
```

Keep temp paths workspace-local. The wrapper and Compose set `TMP`, `TEMP`, `TMPDIR`, and `PYTEST_DEBUG_TEMPROOT` under `tmp/` to avoid unreliable host temp behavior.

## Project Defaults

- Treat PatchPilot as the X-ARC assignment implementation, not a generic agent demo.
- Preserve the fake-model path for deterministic offline tests.
- Use live OpenRouter evaluation only when `.env` is configured and the user expects network/model cost.
- Generated traces, reports, caches, virtualenvs, `.env`, and `tmp/` are local artifacts and must not be committed.
