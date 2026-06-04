# PatchPilot

PatchPilot is a repository repair agent for bounded maintenance loops. It inspects a local repo, reproduces failures, asks a real model to choose phase-scoped tools, delegates diagnosis and review to scoped subagents, creates a typed patch plan, validates the patch before writing, applies the patch, reruns tests, and emits an auditable JSON report plus JSONL trace.

The v1 focus is Python/pytest repair on small product repositories. The demo repository is mocked and controlled, but the agent path is real: OpenRouter model calls, model-selected tools, structured subagent outputs, patch validation, file writes, tests, and final report generation all run through PatchPilot.

## What v1 Can Do

- Repair a failing Python/pytest fixture repository through the real OpenRouter provider.
- Use configurable OpenRouter models such as `z-ai/glm-4.7-flash` or `minimax/minimax-m3`.
- Run phase-scoped tool selection across inspect, reproduce, diagnose, plan patch, apply patch, validate, review, and report.
- Spawn isolated diagnosis and review subagents with scoped tools and structured output schemas.
- Generate a typed `PatchPlan`, validate changed files, protected paths, diff size, and test-only edits before writes.
- Apply a minimal source patch and rerun targeted plus full pytest validation.
- Produce a final JSON report with status, root cause, changed files, tests run, subagents, model/provider, cost metadata, tool count, and trace ID.
- Score a smoke eval from persisted traces and final reports rather than private runtime state.

## Setup

Use Python 3.11+.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

For live model runs, set an OpenRouter key. The CLI also reads `.env` when present.

```powershell
$env:OPENROUTER_API_KEY = "..."
```

Optional model configuration:

- `PATCHPILOT_MODEL`
- `PATCHPILOT_BASE_URL`
- `PATCHPILOT_MODEL_PROVIDER`
- `PATCHPILOT_MAX_MODEL_CALLS`
- `PATCHPILOT_PROMPT_CACHE`

## Real Model Demo

Primary v1 demo:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli run `
  --repo fixtures\mock-store-python `
  --goal "Fix the failing pytest test" `
  --allow-exec `
  --allow-write `
  --model-provider openrouter `
  --model minimax/minimax-m3
```

Default GLM path:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli run `
  --repo fixtures\mock-store-python `
  --goal "Fix the failing pytest test" `
  --allow-exec `
  --allow-write `
  --model-provider openrouter `
  --model z-ai/glm-4.7-flash
```

The run prints a final JSON report to stdout and records the same report as a `run.completed` trace event under:

```text
fixtures/mock-store-python/.patchpilot/traces/
```

## Smoke Eval

Real OpenRouter smoke eval:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli eval `
  --suite smoke `
  --repo fixtures\mock-store-python `
  --model-provider openrouter `
  --model minimax/minimax-m3 `
  --live-eval
```

A verified MiniMax run produced:

```json
{
  "provider": "openrouter",
  "model": "minimax/minimax-m3-20260531",
  "report_status": "success",
  "score": 1.0,
  "tool_calls": 28,
  "trace_id": "tr_fd1f59f76f87"
}
```

The eval checks confirm 50+ registered tools, real model selections, 20+ tool calls, isolated subagents, structured subagent output, typed model patch planning, source patch application, failing-to-passing pytest validation, and a complete final report.

## Offline Verification

Automated tests and cheap local smoke checks can use the deterministic fake model explicitly:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m patchpilot.cli eval --suite smoke --repo fixtures\buggy-python-repo --model-provider fake
```

The fake provider is a test double. Product and live eval commands should use `--model-provider openrouter`.

## Docker And Wrapper Commands

The PowerShell wrapper uses Docker Compose when available and falls back to the local `.venv`:

```powershell
.\scripts\xarc-test.ps1
.\scripts\xarc-test.ps1 -Target smoke
.\scripts\xarc-test.ps1 -Target live-eval
```

Direct Docker commands:

```bash
docker compose run --rm xarc-test
docker compose run --rm xarc-smoke
docker compose run --rm --env-file .env xarc-live-eval
docker compose run --rm xarc-shell
```

## Fixtures

- `fixtures/mock-store-python`: primary v1 demo repo. It contains a tiny ecommerce-style Python app where `apply_discount` subtracts the raw percent value instead of applying it as a percentage. The expected repair changes `mock_store/pricing.py`.
- `fixtures/buggy-python-repo`: deterministic arithmetic repair fixture used by fake-provider tests.
- `fixtures/buggy-validation-repo`: validation branch fixture.
- `fixtures/buggy-parser-repo`: parser delimiter fixture with parametrized pytest failures.

## Trace Inspection

List tools:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli tools list
```

Show a trace:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli trace show tr_fd1f59f76f87 --trace-dir fixtures\mock-store-python\.patchpilot\traces
```

Traces include `model.tool_selection`, `tool.started`, `tool.completed`, `subagent.started`, `subagent.completed`, `model.patch_plan`, `plan.updated`, `context.compacted`, and `run.completed` events.
