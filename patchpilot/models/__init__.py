"""Model-provider clients behind PatchPilot's structured model contract."""

from patchpilot.models.base import ModelClient, ToolSelection
from patchpilot.models.openrouter import OpenRouterModelClient

__all__ = ["ModelClient", "OpenRouterModelClient", "ToolSelection"]
