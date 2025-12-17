"""wt-compiler: Workflow compiler for generating DAG artifacts from specifications.

This package provides the core compilation functionality for the wt (workflow toolkit)
ecosystem. It converts workflow specifications (spec.yaml files) into complete,
executable workflow packages with DAGs, parameter models, CLIs, and deployment configs.

Main exports:
- DagCompiler: Main compiler class
- Spec: Workflow specification model
- compile_workflow: Convenience function for compilation
- discover_tasks_from_requirements: Task discovery via wt-registry CLI
"""

from wt_compiler.compiler import DagCompiler, Fingerprint, compile_workflow
from wt_compiler.discovery import (
    discover_tasks_from_requirements,
    discover_tasks_from_spec_requirements,
    populate_known_tasks,
)
from wt_compiler.spec import (
    KnownTask,
    Spec,
    SpecRequirement,
    TaskGroup,
    TaskInstance,
    TaskTag,
)

__all__ = [
    # Core compilation
    "DagCompiler",
    "Fingerprint",
    "compile_workflow",
    # Discovery
    "discover_tasks_from_requirements",
    "discover_tasks_from_spec_requirements",
    "populate_known_tasks",
    # Spec models
    "Spec",
    "SpecRequirement",
    "TaskInstance",
    "TaskGroup",
    "KnownTask",
    "TaskTag",
]

try:
    from wt_compiler._version import __version__
except ImportError:
    __version__ = "unknown"
