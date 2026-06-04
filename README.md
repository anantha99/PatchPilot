# PatchPilot

PatchPilot is a production-shaped repository automation agent for bounded maintenance loops. It inspects a local repository, reproduces failures, delegates diagnosis and review to scoped subagents, plans and applies minimal patches, validates with tests, and emits an auditable trace.

The v1 target is Python/pytest reliability with a language-agnostic core and generic `--test-command` support for other stacks. Product and eval runs default to OpenRouter with GLM-4.7 Flash (`z-ai/glm-4.7-flash`); deterministic fake models remain available only as an explicit offline/test path.

See [PRODUCT.md](PRODUCT.md) and [PRD.md](PRD.md) for the project plan.

## Quick Start

For agent and CI verification, prefer the canonical wrapper:

```powershell
.\scripts\xarc-test.ps1
.\scripts\xarc-test.ps1 -Target smoke
.\scripts\xarc-test.ps1 -Target live-eval
```

The wrapper uses Docker Compose when available and falls back to the local `.venv` with workspace-local temp paths. Direct Docker commands are also available:

```bash
docker compose run --rm xarc-test
docker compose run --rm xarc-smoke
docker compose run --rm --env-file .env xarc-live-eval
docker compose run --rm xarc-shell
```

```bash
patchpilot tools list
set OPENROUTER_API_KEY=...
patchpilot run --repo fixtures/mock-store-python --goal "Fix the failing pytest test" --allow-exec --allow-write --model-provider openrouter --model z-ai/glm-4.7-flash
patchpilot eval --suite smoke --repo fixtures/mock-store-python --live-eval
```

Offline tests and local deterministic demos can opt into the fake model explicitly:

```bash
patchpilot run --repo fixtures/buggy-python-repo --goal "repair failing pytest" --allow-exec --allow-write --model-provider fake
patchpilot eval --suite smoke --repo fixtures/buggy-python-repo --model-provider fake
```

`PATCHPILOT_MODEL`, `PATCHPILOT_BASE_URL`, `PATCHPILOT_MODEL_PROVIDER`, `PATCHPILOT_MAX_MODEL_CALLS`, and `PATCHPILOT_PROMPT_CACHE` can override model behavior. Traces record provider/model, model lifecycle events, token/cost/cache metadata when OpenRouter returns it, and typed failures when a model response is invalid.

## What The Demo Proves

- 50+ registered typed tools across filesystem, git, code, exec, memory/eval, and subagent namespaces.
- Tool calls resolve through `ToolRegistry` and `ToolExecutor` with schema validation, permission gates, retries, rate limits, and JSONL traces.
- The repair loop records `model.tool_selection` before execution and produces 20+ tool calls in one coherent session.
- `subagent.spawn_diagnosis` and `subagent.spawn_review` run isolated scoped child contexts, expose child trace spans, and return structured diagnosis/review results.
- Patch writes go through evidence, a typed patch plan, validation for repo containment/protected paths/diff size/test-only fixes, and `fs.apply_patch`.
- Eval scoring reads persisted traces and final reports rather than private runtime objects.

Trace files are written under `.patchpilot/traces` inside the repaired repository by default.

## Fixture Set

- `fixtures/mock-store-python`: primary v1 demo repo. A small ecommerce-style Python app with a discount bug repaired through the real OpenRouter/GLM path.
- `fixtures/buggy-python-repo`: arithmetic source bug used by the deterministic smoke repair.
- `fixtures/buggy-validation-repo`: inverted validation branch.
- `fixtures/buggy-parser-repo`: parser delimiter bug with parametrized pytest failures.

Each fixture keeps generated `.patchpilot`, `.pytest_cache`, and `__pycache__` artifacts out of copied eval workspaces.

## Public Repo Hygiene

Do not commit `.env`, generated `.patchpilot/` traces, local virtualenvs, pytest caches, or host-specific temp output. Curated demo traces or eval JSON should be reviewed for API keys and local paths before publication.
