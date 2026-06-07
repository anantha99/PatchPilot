"""Tool registry tests for namespace, schema, and metadata coherence."""

from pydantic import BaseModel
import pytest

from patchpilot.errors import ToolError
from patchpilot.schemas.common import Permission, ToolNamespace
from patchpilot.tools import build_registry
from patchpilot.tools.registry import ToolRegistry


class In(BaseModel):
    pass


class Out(BaseModel):
    ok: bool = True


async def handler(input: In, context) -> Out:
    return Out()


def test_registry_has_assignment_inventory() -> None:
    registry = build_registry()
    tools = registry.list()

    assert len(tools) >= 50
    assert len(registry.namespaces()) >= 4
    assert all(tool.name.startswith(f"{tool.namespace.value}.") for tool in tools)
    assert all(tool.input_schema and tool.output_schema and tool.handler for tool in tools)


def test_duplicate_registration_fails() -> None:
    registry = ToolRegistry()
    registry.register(build_registry().get("fs.list_dir"))
    with pytest.raises(ToolError):
        registry.register(build_registry().get("fs.list_dir"))


def test_namespace_prefix_is_enforced() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolError):
        registry.tool(
            name="wrong.name",
            namespace=ToolNamespace.FS,
            description="bad",
            input_schema=In,
            output_schema=Out,
            permission=Permission.READ,
        )(handler)
