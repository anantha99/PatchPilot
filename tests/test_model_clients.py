import asyncio

from patchpilot.models.fake import FakeModelClient
from patchpilot.runtime.state import SessionState


def test_fake_model_produces_structured_tool_selection(tmp_path) -> None:
    model = FakeModelClient()
    state = SessionState(repo=tmp_path, goal="repair")

    selection = asyncio.run(model.select_tool(state, []))

    assert selection.tool_name == "memory_eval.mark_phase"
    assert selection.arguments["phase"] == "inspect"
