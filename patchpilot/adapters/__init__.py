"""Runtime adapters that normalize repo-specific validation commands."""

from patchpilot.adapters.generic_command import GenericCommandAdapter
from patchpilot.adapters.python_pytest import PythonPytestAdapter

__all__ = ["GenericCommandAdapter", "PythonPytestAdapter"]
