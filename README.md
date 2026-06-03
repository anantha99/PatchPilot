# PatchPilot

PatchPilot is a production-shaped repository automation agent for bounded maintenance loops. It inspects a local repository, reproduces failures, delegates diagnosis and review to scoped subagents, plans and applies minimal patches, validates with tests, and emits an auditable trace.

The v1 target is Python/pytest reliability with a language-agnostic core and generic `--test-command` support for other stacks.

See [PRODUCT.md](PRODUCT.md) and [PRD.md](PRD.md) for the project plan.

