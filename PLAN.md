# Refactoring Plan: ecoscope-workflows → wt Namespace Packages

## Overview

This plan refactors the legacy ecoscope-workflows codebase into modular, independent wt namespace packages. The key architectural innovation is **separation of serializable metadata (`@register`) from execution features (`@task`)**, enabling cross-environment discovery via CLI serialization boundary.

## Architecture Summary

### New Packages (all independent)
1. **wt-registry**: Function registration with JSON schema generation (moved from ../wt-registry)
2. **wt-task**: Task decorator with execution features (map, partial, validation, tracing, error handling)
3. **wt-compiler**: Workflow spec compilation to DAG artifacts (shells out to wt-registry CLI)
4. **wt-invokers**: Abstract invoker interface + implementations (local, GCP Cloud Batch)
5. **wt-runner**: FastAPI application for workflow execution (depends on wt-invokers only)

### Key Design Decisions
- **Decorator pattern**: Task library authors use `@register` only. Generated code wraps functions with `task(registered_func).partial(...).map(...)`
- **Dual-purpose task**: `task` works as both decorator (legacy compat) AND wrapper function
- **Zero Python dependencies**: wt-compiler discovers tasks by creating ephemeral rattler environments and calling wt-registry CLI (subprocess)
- **JSON serialization boundary**: wt-registry CLI outputs complete JSON with metadata + schemas
- **Independence**: All packages independent except wt-runner → wt-invokers
- **Backward compatibility**: ecoscope-workflows updated to use wt packages internally, examples work with minor import changes

---

## Implementation Phases

### Phase 1: Move and Enhance wt-registry

**Goal**: Move wt-registry into wt/ directory and ensure CLI outputs complete JSON with all metadata and schemas needed by compiler.

**Tasks**:
1. Move `../wt-registry/` into `wt/wt-registry/`
2. Update any references to the old location
3. Review current CLI output format (cli.py:60-103 `serialize_entries`)
4. Verify JSON includes all required fields:
   - Function metadata (title, description, tags, deprecated, deprecation_message)
   - Module path and function name
   - JSON schema (parameters + return type)
   - Import statement
5. Test CLI with various function signatures (optional params, complex types, generics)
6. Document expected JSON format for compiler consumption

**Files Modified**:
- Move entire `../wt-registry/` directory to `wt/wt-registry/`
- `wt/wt-registry/src/wt_registry/cli.py` (potentially enhance if needed)
- `wt/wt-registry/tests/test_cli.py` (add comprehensive tests)

**Success Criteria**:
- CLI outputs valid JSON with all metadata
- JSON includes parameter + return type schemas
- Works with complex type annotations

---

### Phase 2: Create wt-task Package

**Goal**: Port task decorator and execution features from legacy decorators.py into standalone wt-task package.

**Source Files** (from ecoscope-workflows-core):
- `ecoscope_workflows_core/decorators.py` (642 lines) → Main decorator logic
- `ecoscope_workflows_core/executors/` → Execution backends
  - `base.py` → Abstract executor interfaces
  - `python.py` → Python executor (sync/async)
  - `lithops.py` → Lithops executor (distributed)
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
│   │   ├── python.py        # PythonExecutor
│   │   └── lithops.py       # LithopsExecutor (optional dependency)
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

1. **Dual-purpose `task` function**:
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

2. **Remove registry dependencies**: No imports from wt-registry or legacy registry module

3. **Preserve execution features**:
   - `.partial()` → Partial function application
   - `.call()` → Direct execution
   - `.map()` → Map over iterables
   - `.mapvalues()` → Map over key-value pairs
   - `.validate()` → Pydantic validation
   - `.with_tracing()` → OpenTelemetry tracing
   - `.handle_errors()` → Error handling wrapper
   - `.skipif()` → Conditional skipping
   - `.set_executor()` → Custom executor

4. **Dependencies**:
   - Core: `pydantic>=2.0.0`, `typing-extensions` (for Python 3.10)
   - Optional: `opentelemetry-api` (for tracing), `lithops` (for distributed execution)

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

**Goal**: Port invoker abstractions and implementations into standalone wt-invokers package.

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

1. **Make GCP dependencies optional**:
   ```toml
   [project]
   dependencies = ["rattler>=0.8.0"]

   [project.optional-dependencies]
   gcp = ["google-cloud-batch>=1.0.0", "google-auth>=2.0.0"]
   dev = ["pytest>=7.0.0", "pytest-cov>=4.0.0", ...]
   ```

2. **Clean imports**:
   - Remove ecoscope-specific imports
   - Use rattler.MatchSpec (already used)

3. **Abstract interface** (preserve as-is):
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

4. **No dependencies on other wt packages**

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

**Goal**: Port compiler logic with rattler environment creation and wt-registry CLI subprocess calls.

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
├── pyproject.toml           # Deps: pydantic, jinja2, ruamel.yaml, rattler-py, datamodel-code-generator
├── src/wt_compiler/
│   ├── __init__.py          # Export: DagCompiler, Spec, compile_workflow
│   ├── spec.py              # Spec, TaskInstance models (from compiler.py)
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

1. **Task discovery via CLI** (NEW - `discovery.py`):
   ```python
   def discover_tasks_from_requirements(
       requirements: list[MatchSpec],
   ) -> dict[str, dict[str, Any]]:
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

           # Parse JSON output
           return json.loads(result.stdout)
   ```

2. **Remove direct Python imports of tasks**:
   - Legacy: `from ecoscope_workflows_core.registry import known_tasks`
   - New: Call `discover_tasks_from_requirements()` to get metadata

3. **Preserve artifact generation**:
   - DAG Python code generation
   - Dockerfile
   - pixi.toml
   - Tests
   - Make outputs configurable (via Spec model), current as defaults

4. **Variable reference parsing** (preserve as-is):
   - `${{ workflow.task_id.return }}`
   - `${{ env.VAR }}`
   - `${{ params.field }}`

5. **Dependencies**:
   - Core: `pydantic>=2.0.0`, `jinja2`, `ruamel.yaml`, `rattler>=0.8.0`, `datamodel-code-generator`
   - NO Python import dependency on wt-registry (subprocess only)

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

1. **Phase 1** (wt-registry enhancement) → Required by Phase 4
2. **Phase 2** (wt-task) → Independent, can start early
3. **Phase 3** (wt-invokers) → Independent
4. **Phase 4** (wt-compiler) → Depends on Phase 1 (wt-registry CLI)
5. **Phase 5** (wt-runner) → Depends on Phase 3 (wt-invokers)
6. **Phase 6** (ecoscope-workflows) → Depends on Phases 2, 4, 5
7. **Phase 7** (task libraries) → Depends on Phase 6

**Parallelization opportunities**:
- Phases 2 & 3 can be done in parallel (both independent)
- Phase 1 must complete before Phase 4

---

## Critical Files Reference

### Source Files (Legacy)
- `ecoscope-workflows/src/ecoscope-workflows-core/ecoscope_workflows_core/decorators.py` (642 lines)
- `ecoscope-workflows/src/ecoscope-workflows-core/ecoscope_workflows_core/compiler.py` (1321 lines)
- `ecoscope-workflows/src/ecoscope-workflows-core/ecoscope_workflows_core/registry.py` (215 lines)
- `ecoscope-workflows/src/ecoscope-workflows-runner/ecoscope_workflows_runner/invokers/`
- `ecoscope-workflows/src/ecoscope-workflows-runner/ecoscope_workflows_runner/app.py` (510 lines)

### Target Packages
- `wt/wt-registry/` (moved from ../wt-registry)
- `wt/wt-task/` (NEW)
- `wt/wt-compiler/` (NEW)
- `wt/wt-invokers/` (NEW)
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
1. All 5 packages in wt/ directory and installable
2. All packages have >90% test coverage
3. Type checking passes (mypy strict)
4. ecoscope-workflows examples work with same behavior
5. Task libraries discoverable via wt-registry CLI
6. Compiler generates correct artifacts using CLI discovery
7. Runner executes workflows correctly
8. Zero circular dependencies
9. Clean separation of concerns (metadata vs execution)

**Ready for production when**:
- All tests pass across all packages
- Examples run successfully
- Documentation complete
- Migration guide written
