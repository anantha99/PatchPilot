# PatchPilot X-ARC Memo

## Built

PatchPilot now has a runnable Typer CLI, a coherent typed tool registry, guarded executor policy, six tool namespaces with 50+ concrete tools, OpenRouter/GLM-4.7 Flash as the product/eval default, structured model metadata, a parent repair runtime, GLM-backed typed diagnosis/review/patch-plan contracts, pytest and generic-command adapters, a primary mocked product repo (`fixtures/mock-store-python`), additional focused Python fixture repositories, JSONL traces, final reports, and a smoke eval harness.

## Cut

Deep multi-language repair, hosted CI integration, PR creation, and richer sandboxing are deferred. Fake model scripts remain only as explicit test doubles so offline tests are cheap and repeatable; reviewer-facing product commands default to OpenRouter against mocked product repos.

## More Time

More time would go into stronger patch synthesis for arbitrary failures, deeper stack adapters, richer command sandboxing, CI-backed validation, and more live-model retry recovery examples across public repositories.

## Defended Decision

The runtime keeps product logic in PatchPilot-owned contracts instead of hiding it inside a graph framework. That keeps the assignment proof visible: model selections, registry metadata, executor policy, patch validation, subagent boundaries, traces, and eval checks are all inspectable Python objects and persisted artifacts.
