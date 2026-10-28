"""wt-compiler: Workflow compiler for generating DAG artifacts from specifications.

This package provides the core compilation functionality for the wt (workflow toolkit)
ecosystem. It converts workflow specifications (spec.yaml files) into complete,
executable workflow packages with DAGs, parameter models, CLIs, and deployment configs.

Main exports:
- DagCompiler: Main compiler class
- Spec: Workflow specification model
- compile_workflow_from_yaml: Recommended entry point with automatic task discovery
- compile_workflow_from_env: Solve-free entry point against the resident registry
- compile_workflow: Lower-level compilation (requires known_tasks pre-populated)
- discover_tasks_from_requirements: Task discovery via wt-registry CLI
- resolve_installed_requirements: Check a spec's requirements against the current environment

Composing a solve-free compile out of process: populate the registry with
``populate_known_tasks_in_process``, then feed ``compile_workflow`` a
``merged_default_feature`` built from ``load_default_injections`` +
``compute_merged_default_feature``. That trio is the supported surface for a
caller that owns its own build loop (e.g. a warm compile service). Such a caller
should also run ``resolve_installed_requirements`` first and pass its result as
``compile_workflow``'s ``installed_requirements`` and ``compiled_against``, as
``compile_workflow_from_env`` does; nothing else checks the resident environment.
"""

from wt_compiler.artifacts import (
    VersionYaml,
    WorkflowArtifacts,
    params_sha256_from_readme,
)
from wt_compiler.compiler import (
    DagCompiler,
    Fingerprint,
    compile_workflow,
    compile_workflow_from_env,
    compile_workflow_from_yaml,
    compute_merged_default_feature,
    load_default_injections,
)
from wt_compiler.discovery import (
    discover_tasks_from_requirements,
    discover_tasks_from_spec_requirements,
    discover_tasks_in_process,
    populate_known_tasks,
    populate_known_tasks_in_process,
)
from wt_compiler.exceptions import (
    DiscoveryError,
    EnvironmentCreationError,
    InstalledRequirementsError,
    PyPIInstallError,
    RegistryExecutionError,
    RegistryNotFoundError,
)
from wt_compiler.installed import resolve_installed_requirements
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
    "InstalledRequirementsError",
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
    "VersionYaml",
    "WorkflowArtifacts",
    "compile_workflow",
    "compile_workflow_from_env",
    "compile_workflow_from_yaml",
    "compute_merged_default_feature",
    "discover_tasks_from_requirements",
    "discover_tasks_from_spec_requirements",
    "discover_tasks_in_process",
    "load_default_injections",
    "params_sha256_from_readme",
    "populate_known_tasks",
    "populate_known_tasks_in_process",
    "resolve_installed_requirements",
]

try:
    from wt_compiler._version import __version__
except ImportError:
    __version__ = "unknown"
