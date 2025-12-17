# Refactoring Plan: ecoscope-workflows → wt Namespace Packages

## Overview

This plan refactors the legacy ecoscope-workflows codebase into modular, independent wt namespace packages. The key architectural innovation is **separation of serializable metadata (`@register`) from execution features (`@task`)**, enabling cross-environment discovery via CLI serialization boundary.

## Architecture Summary

### Packages
1. **wt-contracts**: Shared interface definitions and type contracts (Pydantic models, Protocols)
2. **wt-registry**: Function registration with JSON schema generation (moved from ../wt-registry, uses wt-contracts)
3. **wt-task**: Task decorator with execution features (uses wt-contracts for Protocol)
4. **wt-compiler**: Workflow spec compilation to DAG artifacts (uses wt-contracts for schemas)
5. **wt-invokers**: Abstract invoker interface + implementations (uses wt-contracts for CLI contract)
6. **wt-runner**: FastAPI application for workflow execution (depends on wt-invokers)

### Key Design Decisions
- **Shared contracts**: wt-contracts package provides type-safe interface definitions (Pydantic models + Protocols) that all packages depend on for compatibility
- **Decorator pattern**: Task library authors use `@register` only. Generated code wraps functions with `task(registered_func).partial(...).map(...)`
- **Dual-purpose task**: `task` works as both decorator (legacy compat) AND wrapper function
- **Environment isolation**: wt-compiler does not need to be compatible with task library dependencies - it discovers tasks by creating ephemeral rattler environments and calling wt-registry CLI (subprocess)
- **JSON serialization boundary**: wt-registry CLI outputs complete JSON with metadata + schemas (validated against wt-contracts schemas)
- **Independence**: All packages depend only on wt-contracts (lightweight type-only dependency), plus wt-runner → wt-invokers
- **Backward compatibility**: ecoscope-workflows updated to use wt packages internally, examples work with minor import changes

---

## Implementation Phases

### Phase 0: Create wt-contracts Package

**Goal**: Create foundational package containing all shared interface definitions and type contracts.

**Rationale**: Establishes type-safe contracts between packages without implementation dependencies. This enables:
1. **Registry JSON Schema Contract**: wt-compiler deserializes wt-registry CLI output using shared Pydantic models
2. **Task Execution Interface Contract**: wt-compiler generates code against Protocol, wt-task implements it
3. **Generated CLI Contract**: wt-compiler generates CLIs, wt-invokers calls them with shared argument schema

**Target Structure**:
```
wt-contracts/
├── pyproject.toml           # Minimal deps: pydantic>=2.0.0 only
├── src/wt_contracts/
│   ├── __init__.py          # Export all contracts
│   ├── registry.py          # Contract 1: Registry JSON schema
│   ├── task.py              # Contract 2: Task execution Protocol
│   ├── cli.py               # Contract 3: Generated CLI contract
│   └── _version.py
├── tests/
│   ├── test_registry_schema.py
│   ├── test_task_protocol.py
│   └── test_cli_schema.py
└── README.md
```

**Contract Definitions**:

1. **Registry Contract** (`wt_contracts/registry.py`):
   ```python
   from pydantic import BaseModel, Field

   class RegistryMetadata(BaseModel):
       """Metadata for a registered function."""
       title: str
       description: str
       tags: list[str] = Field(default_factory=list)
       deprecated: bool = False
       deprecation_message: str | None = None

   class RegistryEntry(BaseModel):
       """Complete registry entry from CLI output."""
       metadata: RegistryMetadata
       module_path: str
       function_name: str
       import_statement: str
       json_schema: dict  # JSON Schema for function signature

   class RegistryOutput(BaseModel):
       """Top-level schema for wt-registry CLI JSON output."""
       entries: dict[str, RegistryEntry]  # FQN -> Entry
       version: str = "1.0.0"
   ```

2. **Task Protocol** (`wt_contracts/task.py`):
   ```python
   from typing import Protocol, TypeVar, ParamSpec, Callable, Sequence, Any
   from typing_extensions import Self

   P = ParamSpec("P")
   R = TypeVar("R")

   class TaskProtocol(Protocol[P, R]):
       """Protocol defining task execution interface."""

       def partial(self, **kwargs: Any) -> Self: ...
       def call(self, *args: P.args, **kwargs: P.kwargs) -> R: ...
       def map(self, argname: str, argvalues: Sequence[Any], **kwargs: Any) -> Sequence[R]: ...
       def mapvalues(self, argname: str, argvalues: Sequence[tuple[Any, Any]], **kwargs: Any) -> Sequence[tuple[Any, R]]: ...
       def validate(self) -> Self: ...
       def skipif(self, condition: Callable[..., bool]) -> Self: ...
       def set_executor(self, executor: Any) -> Self: ...
   ```

3. **CLI Contract** (`wt_contracts/cli.py`):
   ```python
   from pydantic import BaseModel

   class WorkflowCLIArgs(BaseModel):
       """Standard CLI arguments for generated workflows."""
       params: str  # JSON string or file path
       params_file: str | None = None
       output_dir: str | None = None
       trace_file: str | None = None
       log_level: str = "INFO"

   class WorkflowCLIEnv(BaseModel):
       """Standard environment variables for workflows."""
       WORKFLOW_RUN_ID: str | None = None
       WORKFLOW_TRACE_ENABLED: str = "false"
       WORKFLOW_OUTPUT_DIR: str | None = None
   ```

**Testing Strategy**:
- Schema validation tests (round-trip serialization)
- Protocol structural typing tests
- Version compatibility tests
- Example usage in docstrings

**Success Criteria**:
- Package builds and installs with minimal dependencies (pydantic only)
- All schemas validate correctly
- Protocols type-check correctly with mypy
- Comprehensive documentation with examples
- >90% test coverage

---

### Phase 1: Move and Enhance wt-registry

**Goal**: Move wt-registry into wt/ directory and refactor to use wt-contracts schemas for CLI output.

**Tasks**:
1. Move `../wt-registry/` into `wt/wt-registry/`
2. Update any references to the old location
3. **Add dependency on wt-contracts** to `pyproject.toml`
4. **Refactor to use wt-contracts schemas**:
   - Replace local `RegistryMetadata` model with `wt_contracts.registry.RegistryMetadata`
   - Replace local `RegistryEntry` model with `wt_contracts.registry.RegistryEntry`
   - Update CLI to output `wt_contracts.registry.RegistryOutput` format
5. Review current CLI output format (cli.py:60-103 `serialize_entries`)
6. Verify JSON includes all required fields matching wt-contracts schema
7. Test CLI with various function signatures (optional params, complex types, generics)
8. Document expected JSON format for compiler consumption

**Files Modified**:
- Move entire `../wt-registry/` directory to `wt/wt-registry/`
- `wt/wt-registry/pyproject.toml` (add wt-contracts dependency)
- `wt/wt-registry/src/wt_registry/models.py` (use wt-contracts models)
- `wt/wt-registry/src/wt_registry/cli.py` (output wt-contracts format)
- `wt/wt-registry/tests/test_cli.py` (validate against wt-contracts schemas)

**Success Criteria**:
- CLI outputs valid JSON matching `wt_contracts.registry.RegistryOutput` schema
- JSON includes parameter + return type schemas
- Works with complex type annotations
- Validates against wt-contracts Pydantic models

---

### Phase 2: Create wt-task Package

**Goal**: Port task decorator and execution features from legacy decorators.py into standalone wt-task package, implementing wt-contracts TaskProtocol.

**Source Files** (from ecoscope-workflows-core):
- `ecoscope_workflows_core/decorators.py` (642 lines) → Main decorator logic
- `ecoscope_workflows_core/executors/` → Execution backends
  - `base.py` → Abstract executor interfaces
  - `python.py` → Python executor (sync/async)
- `ecoscope_workflows_core/skip.py` → Skip sentinel and skipif logic
- `ecoscope_workflows_core/tracing.py` → OpenTelemetry tracing
- `ecoscope_workflows_core/exceptions.py` → Error handling
- `ecoscope_workflows_core/validation.py` → Validation utilities (if exists)

**Target Structure**:
```
wt-task/
├── pyproject.toml           # hatchling build, pydantic + opentelemetry deps
├── src/wt_task/
│   ├── __init__.py          # Export: task, SyncTask, AsyncTask
│   ├── decorator.py         # @task decorator (dual-purpose: decorator + wrapper)
│   ├── base.py              # _Task base class
│   ├── sync_task.py         # SyncTask implementation
│   ├── async_task.py        # AsyncTask implementation
│   ├── executors/
│   │   ├── __init__.py
│   │   ├── base.py          # Abstract executor interfaces
│   │   └── python.py        # PythonExecutor
│   ├── skip.py              # Skip sentinel and skipif
│   ├── tracing.py           # OpenTelemetry integration
│   ├── exceptions.py        # Error handling decorators
│   └── _version.py          # VCS versioning
├── tests/
│   ├── test_decorator.py
│   ├── test_partial.py
│   ├── test_map.py
│   ├── test_mapvalues.py
│   ├── test_executors.py
│   ├── test_skip.py
│   ├── test_tracing.py
│   └── test_validation.py
└── README.md
```

**Key Adaptations**:

1. **Implement TaskProtocol from wt-contracts**:
   - `SyncTask` and `AsyncTask` must implement `wt_contracts.task.TaskProtocol`
   - Ensures type-safe contract with wt-compiler generated code
   - mypy validates Protocol implementation

2. **Dual-purpose `task` function**:
   ```python
   @overload
   def task(func: Callable[P, R]) -> SyncTask[P, R]: ...  # Decorator usage

   @overload
   def task(
       func: Callable[P, R],
       tags: list[str] | None = None,
       description: str | None = None,
   ) -> SyncTask[P, R]: ...  # Wrapper usage

   def task(
       func: Callable[P, R] | None = None,
       *,
       tags: list[str] | None = None,
       description: str | None = None,
   ) -> SyncTask[P, R] | Callable[[Callable[P, R]], SyncTask[P, R]]:
       """
       Decorator and wrapper for task functions.

       Usage as decorator:
           @task
           def my_func(x: int) -> str: ...

       Usage as wrapper (in generated code):
           task(registered_func).partial(x=1).map(...)
       """
       ...
   ```

3. **Remove registry dependencies**: No imports from wt-registry or legacy registry module (only wt-contracts dependency)

4. **Preserve execution features**:
   - `.partial()` → Partial function application
   - `.call()` → Direct execution
   - `.map()` → Map over iterables
   - `.mapvalues()` → Map over key-value pairs
   - `.validate()` → Pydantic validation
   - `.with_tracing()` → OpenTelemetry tracing
   - `.handle_errors()` → Error handling wrapper
   - `.skipif()` → Conditional skipping
   - `.set_executor()` → Custom executor

5. **Dependencies**:
   - Core: `wt-contracts>=0.1.0`, `pydantic>=2.0.0`, `typing-extensions` (for Python 3.10)
   - Optional: `opentelemetry-api` (for tracing)

**Testing Strategy**:
- Port existing tests from ecoscope-workflows-core/tests/
- Add tests for dual-purpose task function
- Test all execution patterns (call, map, mapvalues)
- Test executor switching
- Test skip logic, tracing, error handling

**Success Criteria**:
- All tests pass (>90% coverage)
- `task` works as both decorator and wrapper
- Type checking passes (mypy strict mode)
- No dependencies on wt-registry or other wt packages

---

### Phase 3: Create wt-invokers Package

**Goal**: Port invoker abstractions and implementations into standalone wt-invokers package, using wt-contracts for CLI calling convention.

**Source Files** (from ecoscope-workflows-runner):
- `ecoscope_workflows_runner/invokers/abstract.py` → AbstractInvoker base class
- `ecoscope_workflows_runner/invokers/local.py` → LocalSubprocessInvoker
- `ecoscope_workflows_runner/invokers/cloud_batch.py` → CloudBatchInvoker (GCP)

**Target Structure**:
```
wt-invokers/
├── pyproject.toml           # Core deps: rattler-py; Optional: google-cloud-batch
├── src/wt_invokers/
│   ├── __init__.py          # Export: AbstractInvoker, LocalSubprocessInvoker, etc.
│   ├── abstract.py          # AbstractInvoker ABC
│   ├── local.py             # LocalSubprocessInvoker
│   ├── cloud_batch.py       # CloudBatchInvoker
│   └── _version.py
├── tests/
│   ├── test_abstract.py
│   ├── test_local.py
│   └── test_cloud_batch.py  # Requires GCP credentials (skip in CI)
└── README.md
```

**Key Adaptations**:

1. **Use wt-contracts for CLI contract**:
   - Import `wt_contracts.cli.WorkflowCLIArgs` for subprocess argument construction
   - Import `wt_contracts.cli.WorkflowCLIEnv` for environment variable setup
   - Ensures invokers call generated CLIs with correct interface

2. **Make GCP dependencies optional**:
   ```toml
   [project]
   dependencies = ["wt-contracts>=0.1.0", "rattler>=0.8.0"]

   [project.optional-dependencies]
   gcp = ["google-cloud-batch>=1.0.0", "google-auth>=2.0.0"]
   dev = ["pytest>=7.0.0", "pytest-cov>=4.0.0", ...]
   ```

3. **Clean imports**:
   - Remove ecoscope-specific imports
   - Use rattler.MatchSpec (already used)

4. **Abstract interface** (preserve as-is):
   ```python
   class AbstractInvoker(ABC):
       @abstractmethod
       def is_installed(self, workflow: MatchSpec) -> bool: ...

       @abstractmethod
       def install(self, workflow: MatchSpec) -> None: ...

       @abstractmethod
       def run(self, workflow: MatchSpec, params: dict[str, Any]) -> Any: ...

       @abstractmethod
       def wait(self) -> int: ...

       @property
       @abstractmethod
       def is_waitable(self) -> bool: ...
   ```

5. **Dependencies**: Only wt-contracts (no other wt packages)

**Testing Strategy**:
- Unit tests for abstract interface
- Integration tests for LocalSubprocessInvoker
- Mock tests for CloudBatchInvoker (avoid real GCP calls)

**Success Criteria**:
- All tests pass
- GCP dependencies are optional (package installs without them)
- Type checking passes
- No dependencies on other wt packages

---

### Phase 4: Create wt-compiler Package

**Goal**: Port compiler logic with rattler environment creation and wt-registry CLI subprocess calls, using wt-contracts for schema deserialization and code generation.

**Source Files** (from ecoscope-workflows-core):
- `ecoscope_workflows_core/compiler.py` (1321 lines) → Main compiler logic
- `ecoscope_workflows_core/artifacts.py` → Artifact generation (Dockerfile, pixi.toml, tests)
- `ecoscope_workflows_core/templates/` → Jinja2 templates
- `ecoscope_workflows_core/jsonschema.py` → JSON schema utilities
- `ecoscope_workflows_core/requirements.py` → Requirement handling
- `ecoscope_workflows_core/util.py` → Import reference utilities

**Target Structure**:
```
wt-compiler/
├── pyproject.toml           # Deps: wt-contracts, pydantic, jinja2, ruamel.yaml, rattler-py, datamodel-code-generator
├── src/wt_compiler/
│   ├── __init__.py          # Export: DagCompiler, Spec, compile_workflow
│   ├── spec.py              # Spec, TaskInstance models (STAYS in wt-compiler, not wt-contracts)
│   ├── compiler.py          # DagCompiler class
│   ├── discovery.py         # NEW: Task discovery via rattler + wt-registry CLI
│   ├── artifacts.py         # Artifact generation
│   ├── templates/           # Jinja2 templates (copied from legacy)
│   │   ├── dag.py.jinja
│   │   ├── Dockerfile.jinja
│   │   ├── pixi.toml.jinja
│   │   └── test_dag.py.jinja
│   ├── jsonschema.py        # JSON schema utilities
│   ├── requirements.py      # Requirement handling
│   ├── util.py              # Import utilities
│   └── _version.py
├── tests/
│   ├── test_spec.py
│   ├── test_compiler.py
│   ├── test_discovery.py
│   ├── test_artifacts.py
│   └── fixtures/
│       └── sample_specs/
└── README.md
```

**Key Adaptations**:

1. **Spec model stays in wt-compiler** (architectural decision):
   - `Spec` and `TaskInstance` models define workflow input format (spec.yaml)
   - These are **not** inter-package interfaces - only wt-compiler needs them
   - If wt-runner eventually needs to compile specs, it will depend on wt-compiler
   - wt-contracts is reserved for interfaces **between** packages, not package inputs

2. **Use wt-contracts for deserialization**:
   - Import `wt_contracts.registry.RegistryOutput` to deserialize wt-registry CLI JSON
   - Import `wt_contracts.task.TaskProtocol` to type-check generated code
   - Import `wt_contracts.cli.WorkflowCLIArgs` to generate standard CLI interface
   - Ensures type-safe contract with both registry and task packages

2. **Task discovery via CLI** (NEW - `discovery.py`):
   ```python
   from wt_contracts.registry import RegistryOutput

   def discover_tasks_from_requirements(
       requirements: list[MatchSpec],
   ) -> RegistryOutput:
       """
       Discover tasks by creating ephemeral rattler environment.

       1. Use rattler-py solve/install API to create temp env
       2. Call wt-registry CLI in that environment
       3. Parse JSON output
       4. Return dict of FQN -> metadata
       """
       with tempfile.TemporaryDirectory() as tmpdir:
           env_path = Path(tmpdir) / "env"

           # Solve and install requirements using rattler-py
           solved = rattler.solve(
               specs=requirements,
               channels=["conda-forge"],
               platforms=["linux-64"],
           )
           rattler.install(solved, target_prefix=env_path)

           # Call wt-registry CLI in the environment
           result = subprocess.run(
               [env_path / "bin" / "wt-registry", "--format", "json"],
               capture_output=True,
               text=True,
               check=True,
           )

           # Parse and validate JSON output using wt-contracts schema
           return RegistryOutput.model_validate_json(result.stdout)
   ```

3. **Remove direct Python imports of tasks**:
   - Legacy: `from ecoscope_workflows_core.registry import known_tasks`
   - New: Call `discover_tasks_from_requirements()` to get `RegistryOutput` with type-safe metadata

4. **Preserve artifact generation**:
   - DAG Python code generation
   - Dockerfile
   - pixi.toml
   - Tests
   - Make outputs configurable (via Spec model), current as defaults

5. **Variable reference parsing** (preserve as-is):
   - `${{ workflow.task_id.return }}`
   - `${{ env.VAR }}`
   - `${{ params.field }}`

6. **Dependencies**:
   - Core: `wt-contracts>=0.1.0`, `pydantic>=2.0.0`, `jinja2`, `ruamel.yaml`, `rattler>=0.8.0`, `datamodel-code-generator`
   - NO Python import dependency on wt-registry or wt-task (only wt-contracts for types)

**Testing Strategy**:
- Unit tests for spec parsing
- Integration tests for task discovery (requires wt-registry installed)
- Tests for artifact generation
- Mock rattler environment creation in some tests

**Success Criteria**:
- Compiler discovers tasks via CLI (no direct Python imports)
- All artifact types generated correctly
- Tests pass
- No Python import dependency on wt-registry

---

### Phase 5: Create wt-runner Package

**Goal**: Port FastAPI application for workflow execution.

**Source Files** (from ecoscope-workflows-runner):
- `ecoscope_workflows_runner/app.py` (510 lines) → FastAPI app
- `ecoscope_workflows_runner/tracing.py` → OpenTelemetry tracing setup

**Target Structure**:
```
wt-runner/
├── pyproject.toml           # Deps: fastapi, uvicorn, wt-invokers
├── src/wt_runner/
│   ├── __init__.py
│   ├── app.py               # FastAPI app
│   ├── tracing.py           # OpenTelemetry tracing
│   └── _version.py
├── tests/
│   ├── test_app.py
│   └── test_endpoints.py
└── README.md
```

**Key Adaptations**:

1. **Depend on wt-invokers**:
   ```python
   from wt_invokers import AbstractInvoker, INVOKERS
   ```

2. **Preserve all endpoints**:
   - `POST /` → Run workflow
   - `POST /run-from-pubsub` → Process Pub/Sub messages
   - `GET /rjsf` → Get JSON schema
   - `GET /data-connection-property-names` → Get data connection metadata
   - `POST /formdata-to-params` → Convert form data
   - `POST /params-to-formdata` → Convert params

3. **Same API contract**: No breaking changes to HTTP API

4. **Dependencies**:
   - Core: `fastapi`, `uvicorn`, `wt-invokers`, `rattler`, `pydantic`
   - Optional: Same as legacy (obstore, opentelemetry, etc.)

**Testing Strategy**:
- FastAPI TestClient for endpoint tests
- Mock invokers for unit tests
- Integration tests with LocalSubprocessInvoker

**Success Criteria**:
- All endpoints work as before
- Tests pass
- API contract unchanged

---

### Phase 6: Update ecoscope-workflows

**Goal**: Update ecoscope-workflows to use wt packages internally while maintaining export compatibility.

**Files to Update**:
- `ecoscope-workflows/src/ecoscope-workflows-core/ecoscope_workflows_core/__init__.py` → Re-export from wt packages
- `ecoscope-workflows/src/ecoscope-workflows-core/pyproject.toml` → Depend on wt packages
- `ecoscope-workflows/src/ecoscope-workflows-runner/ecoscope_workflows_runner/__init__.py` → Re-export from wt packages
- `ecoscope-workflows/src/ecoscope-workflows-runner/pyproject.toml` → Depend on wt packages

**Strategy**:

1. **ecoscope_workflows_core** becomes thin wrapper:
   ```python
   # ecoscope_workflows_core/__init__.py
   from wt_task import task, SyncTask, AsyncTask
   from wt_compiler import DagCompiler, Spec

   # Re-export for backward compatibility
   __all__ = ["task", "SyncTask", "AsyncTask", "DagCompiler", "Spec"]
   ```

2. **ecoscope_workflows_runner** becomes thin wrapper:
   ```python
   # ecoscope_workflows_runner/__init__.py
   from wt_runner import app
   from wt_invokers import AbstractInvoker, LocalSubprocessInvoker

   __all__ = ["app", "AbstractInvoker", "LocalSubprocessInvoker"]
   ```

3. **Update pyproject.toml dependencies**:
   ```toml
   [project]
   dependencies = [
       "wt-task>=0.1.0",
       "wt-compiler>=0.1.0",
       "wt-registry>=0.1.0",
   ]
   ```

4. **Update examples with minor import changes** (examples/ directory):
   - Change: `from ecoscope_workflows_core import task` (unchanged - still works!)
   - Change: `from ecoscope_workflows_core.decorators import task` → `from ecoscope_workflows_core import task`
   - Examples should run with same behavior

**Testing Strategy**:
- Run all existing ecoscope-workflows tests
- Verify examples work correctly
- Check that API exports are identical

**Success Criteria**:
- Examples run with same behavior (minor import changes OK)
- All tests pass
- Export API unchanged (or backward compatible)

---

### Phase 7: Update Task Libraries

**Goal**: Update ecoscope task libraries to use `@register` decorator.

**Task Libraries to Update**:
- `ecoscope-workflows-ext-ecoscope` (main task library)
- Any other task libraries in ecoscope-workflows/src/

**Strategy**:

1. **Add `@register` decorator to all task functions**:
   ```python
   from wt_registry import register

   @register(
       title="Calculate Statistics",
       description="Calculate statistical measures for dataframe",
       tags=["statistics", "dataframe"],
   )
   def calculate_stats(df: pd.DataFrame) -> dict[str, float]:
       return {"mean": df.mean(), "std": df.std()}
   ```

2. **Keep or remove `@task` decorator**:
   - Option A: Remove `@task` (recommended) - generated code will wrap with `task()`
   - Option B: Keep both `@register` and `@task` for direct usage

3. **Update pyproject.toml**:
   ```toml
   [project]
   dependencies = [
       "wt-registry>=0.1.0",
       # ... other deps
   ]
   ```

4. **Test discovery**:
   ```bash
   # In task library environment
   wt-registry --format json | jq '.["ecoscope_ext.calculate_stats"]'
   ```

**Files to Update**:
- All task function definitions in `ecoscope-workflows-ext-ecoscope/`
- `ecoscope-workflows-ext-ecoscope/pyproject.toml`

**Testing Strategy**:
- Test that wt-registry CLI discovers all functions
- Test that JSON output includes schemas
- Test that task functions still execute correctly
- Integration test with wt-compiler

**Success Criteria**:
- All task functions discoverable via wt-registry CLI
- JSON schemas generated correctly
- Functions execute correctly when wrapped with `task()`

---

## Implementation Order

Execute phases **sequentially** in order:

0. **Phase 0** (wt-contracts) → **MUST BE FIRST** - All other packages depend on this
1. **Phase 1** (wt-registry) → Depends on Phase 0
2. **Phase 2** (wt-task) → Depends on Phase 0, can be parallel with Phase 3
3. **Phase 3** (wt-invokers) → Depends on Phase 0, can be parallel with Phase 2
4. **Phase 4** (wt-compiler) → Depends on Phases 0 and 1
5. **Phase 5** (wt-runner) → Depends on Phases 0 and 3
6. **Phase 6** (ecoscope-workflows) → Depends on Phases 1, 2, 4, 5
7. **Phase 7** (task libraries) → Depends on Phase 6

**Critical Path**:
1. Phase 0 (wt-contracts) - foundational
2. Phase 1 (wt-registry) - needed by Phase 4
3. Phase 4 (wt-compiler) - needed by Phase 6
4. Phase 6 (ecoscope-workflows) - needed by Phase 7
5. Phase 7 (task libraries) - final step

**Parallelization opportunities**:
- After Phase 0: Phases 1, 2, and 3 can start in parallel
- After Phase 1: Phase 4 can start while Phases 2/3 continue
- After Phase 3: Phase 5 can start while Phase 4 continues

---

## Versioning and Development Workflow

### Overview

The wt repository is a monorepo containing 6 independently-versioned packages. This requires:
1. **Independent versioning**: Each package has its own semantic version
2. **Automated version derivation**: Versions come from git tags, not manual pyproject.toml edits
3. **Git tag strategy**: Multiple packages in one repo need unique tag naming
4. **Per-package development**: Isolated environments with editable wt-contracts references

---

### 1. Git Tag Strategy

Use prefixed tags following the pattern: `<package-name>/v<semver>`

**Examples**:
```bash
git tag wt-contracts/v0.1.0
git tag wt-registry/v0.2.0
git tag wt-task/v0.1.0
git tag wt-compiler/v0.1.0
git tag wt-invokers/v0.1.0
git tag wt-runner/v0.1.0
```

**Rationale**:
- Industry standard for monorepos (used by Go modules, Rust workspaces, etc.)
- Clear namespace prevents tag collisions
- Tooling can parse package name from tag prefix
- Easy to see all versions: `git tag -l "wt-contracts/*"`

**Tag Lifecycle**:
```bash
# Create annotated tag with release notes
git tag -a wt-contracts/v0.1.0 -m "Release wt-contracts v0.1.0

- Initial release with Registry, Task, and CLI contracts
- Full Pydantic model validation
- Protocol-based task interface"

# Push tag to remote
git push origin wt-contracts/v0.1.0

# List all tags for a package
git tag -l "wt-contracts/*"

# Delete tag (if needed)
git tag -d wt-contracts/v0.1.0
git push origin :refs/tags/wt-contracts/v0.1.0
```

---

### 2. Automated Versioning with setuptools-scm

Use **setuptools-scm** for automatic version derivation from git tags.

**Why setuptools-scm**:
- Mature, battle-tested tool (used by pytest, numpy, scipy, etc.)
- Native monorepo support via `tag_regex` and `root` parameters
- No manual version numbers in pyproject.toml
- Generates version files automatically
- Works with PEP 517 build systems (including uv)

**Configuration per package** (e.g., `wt-contracts/pyproject.toml`):

```toml
[build-system]
requires = ["setuptools>=64", "setuptools-scm>=8"]
build-backend = "setuptools.build_meta"

[project]
name = "wt-contracts"
dynamic = ["version"]
description = "Shared interface contracts for wt packages"
requires-python = ">=3.10"
dependencies = [
    "pydantic>=2.0.0,<3.0.0",
]

[dependency-groups]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "mypy>=1.0.0",
    "ruff>=0.1.0",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools_scm]
# Version comes from git tags matching this pattern
tag_regex = "^wt-contracts/v(?P<version>[0-9.]+)$"
# Root is the git repository root
root = ".."
# Generate version file
version_file = "src/wt_contracts/_version.py"
```

**Key Parameters**:
- `tag_regex`: Matches tags like `wt-contracts/v0.1.0`
- `root = ".."`: Git root is parent directory (monorepo root)
- `version_file`: Auto-generated file with version string

**How It Works**:
1. Developer creates tag: `git tag wt-contracts/v0.1.0`
2. During build, setuptools-scm:
   - Runs `git describe` to find matching tags
   - Parses tag using regex to extract version
   - Generates `_version.py` with version string
   - Injects version into package metadata
3. Between releases: generates dev versions like `0.1.1.dev3+g1a2b3c4`

---

### 3. Per-Package Development Environments

**Philosophy**: Each package gets its own isolated environment (not a unified workspace).

**Why isolated environments**:
- ✅ Most packages only depend on wt-contracts (minimal inter-dependency)
- ✅ Developers typically work on ONE package at a time
- ✅ Faster sync (only install what you need)
- ✅ Realistic testing (matches end-user install experience)
- ✅ Each package independently testable

**Package dependency structure**:
```
wt-contracts (no wt deps)
    ↑
    ├── wt-registry (depends on wt-contracts only)
    ├── wt-task (depends on wt-contracts only)
    ├── wt-compiler (depends on wt-contracts only)
    └── wt-invokers (depends on wt-contracts only)
            ↑
        wt-runner (depends on wt-invokers + wt-contracts)
```

---

### 4. Development with uv and tool.uv.sources

Each package references editable wt-contracts using `[tool.uv.sources]`.

**Example: wt-registry/pyproject.toml**

```toml
[project]
name = "wt-registry"
dynamic = ["version"]
dependencies = [
    "wt-contracts>=0.1.0,<1.0.0",  # WHAT to install (version constraint)
    "pydantic>=2.0.0,<3.0.0",
]

[dependency-groups]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "mypy>=1.0.0",
    "ruff>=0.1.0",
]

[tool.uv.sources]
# WHERE to install from (development override)
wt-contracts = { path = "../wt-contracts", editable = true }

[tool.setuptools_scm]
tag_regex = "^wt-registry/v(?P<version>[0-9.]+)$"
root = ".."
version_file = "src/wt_registry/_version.py"
```

**How [tool.uv.sources] works**:
1. `[project.dependencies]` declares `"wt-contracts>=0.1.0"` is required
2. `[tool.uv.sources]` overrides WHERE to get it (local path instead of PyPI)
3. `uv` installs from `../wt-contracts` in editable mode
4. `uv` validates local version satisfies `>=0.1.0` constraint
5. **Published packages**: `[tool.uv.sources]` is dev-only; end users get from PyPI

**Example: wt-runner/pyproject.toml (multiple wt deps)**

```toml
[project]
name = "wt-runner"
dependencies = [
    "wt-invokers>=0.1.0,<1.0.0",
    "wt-contracts>=0.1.0,<1.0.0",  # Explicit, though transitive via wt-invokers
    "fastapi>=0.100.0",
    "uvicorn>=0.20.0",
]

[dependency-groups]
dev = [
    "pytest>=7.0.0",
    "httpx>=0.24.0",  # For FastAPI testing
]

[tool.uv.sources]
# Reference multiple local packages
wt-contracts = { path = "../wt-contracts", editable = true }
wt-invokers = { path = "../wt-invokers", editable = true }

[tool.setuptools_scm]
tag_regex = "^wt-runner/v(?P<version>[0-9.]+)$"
root = ".."
version_file = "src/wt_runner/_version.py"
```

---

### 5. Developer Workflow

**Working on a single package**:

```bash
# 1. Navigate to package
cd wt/wt-registry

# 2. Create isolated environment and install dependencies
uv sync

# This installs:
# - wt-contracts from ../wt-contracts (editable)
# - pydantic from PyPI
# - dev dependencies (pytest, mypy, ruff)

# 3. Activate environment (optional, uv run works without activation)
source .venv/bin/activate

# 4. Run tests
uv run pytest

# 5. Type check
uv run mypy src/

# 6. Lint
uv run ruff check .

# 7. Make changes to wt-contracts
cd ../wt-contracts
# Edit src/wt_contracts/registry.py

# 8. Changes immediately available in wt-registry (editable install)
cd ../wt-registry
uv run pytest  # Tests see updated wt-contracts
```

**Working on wt-contracts (no dependencies)**:

```bash
cd wt/wt-contracts
uv sync          # Only installs dev deps (no other wt packages)
uv run pytest
uv run mypy src/
```

**Working on wt-runner (depends on wt-invokers)**:

```bash
cd wt/wt-runner
uv sync          # Installs editable wt-contracts + wt-invokers
uv run pytest

# Changes to wt-invokers immediately reflected
cd ../wt-invokers
# Edit src/wt_invokers/local.py
cd ../wt-runner
uv run pytest    # Sees updated wt-invokers
```

**Cross-package testing**:

```bash
# Test wt-registry after updating wt-contracts
cd wt/wt-contracts
# Make breaking change to RegistryEntry

cd ../wt-registry
uv run pytest    # Will fail if incompatible

cd ../wt-compiler
uv run pytest    # Will also fail if incompatible
```

---

### 6. Handling tool.uv.sources for Release

**Important**: `[tool.uv.sources]` should be kept in development but won't affect published packages.

**Why it's safe to keep**:
- When users `pip install wt-registry` from PyPI, they get the built wheel/sdist
- The built package contains resolved dependencies, not the `[tool.uv.sources]` section
- PyPI packages reference other packages normally (e.g., `wt-contracts>=0.1.0` from PyPI)

**Best practice**: Keep `[tool.uv.sources]` in the repository for developer convenience. It only affects local development, not published packages.

**Optional: Comment for clarity**:
```toml
[tool.uv.sources]
# Development override - uses local editable wt-contracts
# Published packages will reference PyPI version normally
wt-contracts = { path = "../wt-contracts", editable = true }
```

---

### 7. Release Process

**Per-Package Release Workflow**:

```bash
# 1. Ensure on main with clean working directory
git checkout main
git pull origin main
git status  # Should be clean

# 2. Run tests for the package
cd wt/wt-contracts
uv run pytest tests/
uv run mypy src/

# 3. Create git tag
git tag -a wt-contracts/v0.1.0 -m "Release wt-contracts v0.1.0

Features:
- Registry JSON schema contract
- Task execution Protocol
- Generated CLI contract
"

# 4. Push tag (triggers version bump via setuptools-scm)
git push origin wt-contracts/v0.1.0

# 5. Build package (version auto-derived from tag)
uv build

# Verify version in dist/
ls dist/
# wt_contracts-0.1.0-py3-none-any.whl
# wt_contracts-0.1.0.tar.gz

# 6. Publish to PyPI
uv publish

# 7. Verify installation
uv pip install wt-contracts==0.1.0 --index-url https://pypi.org/simple/
python -c "import wt_contracts; print(wt_contracts.__version__)"
```

**Releasing dependent packages**:

```bash
# After publishing wt-contracts v0.1.0, publish wt-registry

cd wt/wt-registry

# Ensure pyproject.toml has correct wt-contracts version
# [project]
# dependencies = ["wt-contracts>=0.1.0,<1.0.0"]

git tag -a wt-registry/v0.1.0 -m "Release wt-registry v0.1.0"
git push origin wt-registry/v0.1.0

uv build
uv publish
```

---

### 8. Version Coordination Strategy

**Independent vs Coordinated Releases**:

Use **independent versioning** (recommended): Each package has its own version
- wt-contracts: 0.1.0
- wt-registry: 0.1.0
- wt-task: 0.1.0
- wt-compiler: 0.2.1 (more features)
- wt-invokers: 0.1.2 (bug fix)
- wt-runner: 0.3.0 (breaking change)

**Semantic Versioning (MAJOR.MINOR.PATCH)**:

- **MAJOR** (0.x.0 → 1.0.0): Breaking changes to public API
  - Example: Remove field from TaskProtocol
  - Requires dependent packages to update
- **MINOR** (0.1.0 → 0.2.0): New features, backward compatible
  - Example: Add optional field to RegistryEntry
  - Dependent packages can upgrade without changes
- **PATCH** (0.1.0 → 0.1.1): Bug fixes only
  - Example: Fix CLI parsing bug
  - Safe to upgrade immediately

---

## Critical Files Reference

### Source Files (Legacy)
- `ecoscope-workflows/src/ecoscope-workflows-core/ecoscope_workflows_core/decorators.py` (642 lines)
- `ecoscope-workflows/src/ecoscope-workflows-core/ecoscope_workflows_core/compiler.py` (1321 lines)
- `ecoscope-workflows/src/ecoscope-workflows-core/ecoscope_workflows_core/registry.py` (215 lines)
- `ecoscope-workflows/src/ecoscope-workflows-runner/ecoscope_workflows_runner/invokers/`
- `ecoscope-workflows/src/ecoscope-workflows-runner/ecoscope_workflows_runner/app.py` (510 lines)

### Target Packages
- `wt/wt-contracts/` (NEW - foundational type contracts)
- `wt/wt-registry/` (moved from ../wt-registry, refactored to use wt-contracts)
- `wt/wt-task/` (NEW - implements wt-contracts TaskProtocol)
- `wt/wt-compiler/` (NEW - uses wt-contracts for all schemas)
- `wt/wt-invokers/` (NEW - uses wt-contracts CLI contract)
- `wt/wt-runner/` (NEW)

---

## Testing Strategy

Follow wt-registry testing standards (from CLAUDE.md):
- **Always write unit tests** (>90% coverage)
- **Complete type annotations** (mypy strict mode)
- **Docstrings with examples** (doctests where applicable)
- **Run tests frequently**: `uv run pytest`
- **Quality tools**: mypy, ruff check, ruff format

Each package should have:
- Unit tests for core functionality
- Integration tests with other packages (where applicable)
- Doctest examples in docstrings
- Type checking passing (mypy strict)

---

## Success Criteria

**Overall Project Success**:
1. All 6 packages in wt/ directory and installable
2. All packages have >90% test coverage
3. Type checking passes (mypy strict)
4. wt-contracts provides type-safe interface contracts
5. ecoscope-workflows examples work with same behavior
6. Task libraries discoverable via wt-registry CLI (validated against wt-contracts schemas)
7. Compiler generates correct artifacts using CLI discovery (type-safe via wt-contracts)
8. Runner executes workflows correctly
9. Zero circular dependencies (only wt-contracts as common dependency)
10. Clean separation of concerns (contracts vs metadata vs execution)

**Ready for production when**:
- All tests pass across all packages
- Examples run successfully
- Documentation complete
- Migration guide written
