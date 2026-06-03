# PatchPilot

PatchPilot is a production-shaped repository automation agent for bounded maintenance loops. It inspects a local repository, reproduces failures, delegates diagnosis and review to scoped subagents, plans and applies minimal patches, validates with tests, and emits an auditable trace.

The v1 target is Python/pytest reliability with a language-agnostic core and generic `--test-command` support for other stacks.

See [PRODUCT.md](PRODUCT.md) and [PRD.md](PRD.md) for the project plan.

## Quick Start

```bash
patchpilot tools list
patchpilot run --repo fixtures/buggy-python-repo --goal "repair failing pytest" --allow-exec --allow-write
patchpilot eval --suite smoke --repo fixtures/buggy-python-repo
```

The deterministic smoke path uses `FakeModelClient` so the X-ARC proof is reproducible without live model access. Live OpenRouter support is behind the same model-selection contract and uses `OPENROUTER_API_KEY`.

## What The Demo Proves

- 50+ registered typed tools across filesystem, git, code, exec, memory/eval, and subagent namespaces.
- Tool calls resolve through `ToolRegistry` and `ToolExecutor` with schema validation, permission gates, retries, rate limits, and JSONL traces.
- The repair loop records `model.tool_selection` before execution and produces 20+ tool calls in one coherent session.
- `subagent.spawn_diagnosis` and `subagent.spawn_review` run isolated scoped child contexts and return structured results.
- Eval scoring reads persisted traces and final reports rather than private runtime objects.

Trace files are written under `.patchpilot/traces` inside the repaired repository by default.
