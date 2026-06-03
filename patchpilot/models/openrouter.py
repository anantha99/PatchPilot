"""OpenRouter model client placeholder behind the model contract."""

from __future__ import annotations

import httpx

from patchpilot.config import PatchPilotConfig
from patchpilot.errors import ModelError
from patchpilot.models.base import ModelClient, ToolSelection


class OpenRouterModelClient(ModelClient):
    def __init__(self, config: PatchPilotConfig) -> None:
        self.config = config

    async def select_tool(self, state, tools) -> ToolSelection:
        if not self.config.openrouter_api_key:
            raise ModelError("OPENROUTER_API_KEY is required for live model runs")
        prompt = {
            "goal": state.goal,
            "phase": state.phase,
            "tools": tools,
            "recent_tool_calls": state.tool_history[-5:],
        }
        async with httpx.AsyncClient(base_url=self.config.base_url, timeout=30) as client:
            response = await client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self.config.openrouter_api_key}"},
                json={
                    "model": self.config.model,
                    "messages": [
                        {"role": "system", "content": "Return JSON with tool_name, arguments, rationale, finish."},
                        {"role": "user", "content": str(prompt)},
                    ],
                    "response_format": {"type": "json_object"},
                },
            )
        if response.status_code >= 400:
            raise ModelError("OpenRouter call failed", {"status_code": response.status_code, "body": response.text})
        content = response.json()["choices"][0]["message"]["content"]
        return ToolSelection.model_validate_json(content)
