# PatchPilot X-ARC Memo

## Built

PatchPilot now has a runnable Typer CLI, a coherent typed tool registry, guarded executor policy, six tool namespaces with 50+ concrete tools, deterministic model-driven tool selection, a parent repair runtime, isolated diagnosis/review subagents, pytest and generic-command adapters, fixture repositories, JSONL traces, final reports, and a smoke eval harness.

## Cut

The live OpenRouter client is implemented behind the interface but not used as the release gate. Deep multi-language repair, hosted CI integration, PR creation, and richer sandboxing are deferred. The smoke repair is intentionally deterministic so reviewers can audit the same trace every run.

## More Time

More time would go into stronger patch synthesis for arbitrary failures, deeper stack adapters, richer command sandboxing, CI-backed validation, and a live-model demo with fallback recovery.

## Defended Decision

The runtime keeps product logic in PatchPilot-owned contracts instead of hiding it inside a graph framework. That keeps the assignment proof visible: model selections, registry metadata, executor policy, subagent boundaries, traces, and eval checks are all inspectable Python objects and persisted artifacts.
