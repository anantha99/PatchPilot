"""Tool registration entrypoint for all reviewer-visible namespaces."""

from __future__ import annotations

from importlib import import_module

from patchpilot.tools.registry import ToolRegistry


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()

    for module_name in ("fs", "git", "code", "exec_tools", "session", "subagent"):
        module = import_module(f"patchpilot.tools.{module_name}")
        module.register(registry)
    return registry
