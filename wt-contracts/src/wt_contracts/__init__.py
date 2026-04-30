"""wt-contracts: Shared interface contracts for wt workflow packages.

This package provides type-safe interface definitions (Pydantic models +
Protocols) that enable inter-package compatibility across the wt ecosystem.

Submodules:
    registry: Registry JSON schema contracts (RegistryMetadata, RegistryEntry, RegistryOutput)
    task: Task execution protocol (TaskProtocol)
    cli: Generated CLI contracts (WorkflowCLIArgs, WorkflowCLIEnv)
    formdata: Schema-driven params <-> formdata conversion helpers
"""

from wt_contracts.cli import WorkflowCLIArgs, WorkflowCLIEnv
from wt_contracts.formdata import (
    ValidationError,
    formdata_to_params,
    params_to_formdata,
)
from wt_contracts.registry import RegistryEntry, RegistryMetadata, RegistryOutput
from wt_contracts.task import TaskProtocol

try:
    from wt_contracts._version import __version__
except ImportError:
    # Version file not generated yet (happens during development before first build)
    __version__ = "0.0.0.dev0"

__all__ = [
    # Registry contracts
    "RegistryMetadata",
    "RegistryEntry",
    "RegistryOutput",
    # Task protocol
    "TaskProtocol",
    # CLI contracts
    "WorkflowCLIArgs",
    "WorkflowCLIEnv",
    # Formdata conversion
    "formdata_to_params",
    "params_to_formdata",
    "ValidationError",
    # Version
    "__version__",
]
