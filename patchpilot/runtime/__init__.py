"""Runtime package.

Import concrete runtime classes from their submodules to avoid model/runtime
import cycles during provider initialization.
"""

__all__ = ["RepairRuntime", "SessionState"]


def __getattr__(name: str):
    if name == "RepairRuntime":
        from patchpilot.runtime.graph import RepairRuntime

        return RepairRuntime
    if name == "SessionState":
        from patchpilot.runtime.state import SessionState

        return SessionState
    raise AttributeError(name)
