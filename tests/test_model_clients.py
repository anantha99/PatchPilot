import asyncio

import httpx
import pytest

from patchpilot.config import DEFAULT_MODEL, PatchPilotConfig
from patchpilot.errors import MissingModelApiKeyError, ModelSchemaError
from patchpilot.models.fake import FakeModelClient
from patchpilot.models.openrouter import OpenRouterModelClient
from patchpilot.runtime.state import SessionState


def test_fake_model_produces_structured_tool_selection(tmp_path) -> None:
    model = FakeModelClient()
    state = SessionState(repo=tmp_path, goal="repair")

    selection = asyncio.run(model.select_tool(state, []))

    assert selection.tool_name == "memory_eval.mark_phase"
    assert selection.arguments["phase"] == "inspect"


def test_openrouter_requires_api_key_before_network_call(tmp_path) -> None:
    config = PatchPilotConfig(repo=tmp_path, openrouter_api_key=None)
    model = OpenRouterModelClient(config)

    with pytest.raises(MissingModelApiKeyError):
        asyncio.run(model.select_tool(SessionState(repo=tmp_path, goal="repair"), []))


def test_openrouter_validates_structured_selection_and_metadata(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        assert DEFAULT_MODEL in body
        return httpx.Response(
            200,
            json={
                "id": "gen-123",
                "model": DEFAULT_MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"tool_name":"fs.list_dir","arguments":{"path":"."},"rationale":"inspect","finish":false}'
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                    "cost": 0.0003,
                    "prompt_tokens_details": {"cached_tokens": 4},
                },
            },
        )

    config = PatchPilotConfig(repo=tmp_path, openrouter_api_key="sk-test")
    model = OpenRouterModelClient(config, transport=httpx.MockTransport(handler))

    selection = asyncio.run(model.select_tool(SessionState(repo=tmp_path, goal="repair"), []))

    assert selection.tool_name == "fs.list_dir"
    assert selection.metadata is not None
    assert selection.metadata.provider == "openrouter"
    assert selection.metadata.model == DEFAULT_MODEL
    assert selection.metadata.usage.total_tokens == 18
    assert selection.metadata.cache.cache_read_tokens == 4


def test_openrouter_rejects_malformed_tool_selection(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": '{"tool_name": 5}'}}],
            },
        )

    config = PatchPilotConfig(repo=tmp_path, openrouter_api_key="sk-test")
    model = OpenRouterModelClient(config, transport=httpx.MockTransport(handler))

    with pytest.raises(ModelSchemaError):
        asyncio.run(model.select_tool(SessionState(repo=tmp_path, goal="repair"), []))


def test_openrouter_completes_typed_json_with_metadata(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "gen-json",
                "model": DEFAULT_MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"approved": true, "issues": []}'},
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
            },
        )

    config = PatchPilotConfig(repo=tmp_path, openrouter_api_key="sk-test")
    model = OpenRouterModelClient(config, transport=httpx.MockTransport(handler))

    response = asyncio.run(
        model.complete_json(
            prompt={"task": "review"},
            schema_name="ReviewResult",
            json_schema={"type": "object"},
        )
    )

    assert response.data["approved"] is True
    assert response.metadata is not None
    assert response.metadata.usage.total_tokens == 9
