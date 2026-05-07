"""wt-compiler: Workflow compiler for generating DAG artifacts from specifications.

This package provides the core compilation functionality for the wt (workflow toolkit)
ecosystem. It converts workflow specifications (spec.yaml files) into complete,
executable workflow packages with DAGs, parameter models, CLIs, and deployment configs.

Main exports:
- DagCompiler: Main compiler class
- Spec: Workflow specification model
- compile_workflow_from_yaml: Recommended entry point with automatic task discovery
- compile_workflow: Lower-level compilation (requires known_tasks pre-populated)
- discover_tasks_from_requirements: Task discovery via wt-registry CLI
"""

from wt_compiler.compiler import (
    DagCompiler,
    Fingerprint,
    compile_workflow,
    compile_workflow_from_yaml,
)
from wt_compiler.discovery import (
    discover_tasks_from_requirements,
    discover_tasks_from_spec_requirements,
    populate_known_tasks,
)
from wt_compiler.exceptions import (
    DiscoveryError,
    EnvironmentCreationError,
    PyPIInstallError,
    RegistryExecutionError,
    RegistryNotFoundError,
)
from wt_compiler.spec import (
    KnownTask,
    PyPIRequirement,
    Spec,
    SpecRequirement,
    TaskGroup,
    TaskInstance,
    TaskTag,
)

__all__ = [
    "DagCompiler",
    "DiscoveryError",
    "EnvironmentCreationError",
    "Fingerprint",
    "KnownTask",
    "PyPIInstallError",
    "PyPIRequirement",
    "RegistryExecutionError",
    "RegistryNotFoundError",
    "Spec",
    "SpecRequirement",
    "TaskGroup",
    "TaskInstance",
    "TaskTag",
    "compile_workflow",
    "compile_workflow_from_yaml",
    "discover_tasks_from_requirements",
    "discover_tasks_from_spec_requirements",
    "populate_known_tasks",
]

try:
    from wt_compiler._version import __version__
except ImportError:
    __version__ = "unknown"
