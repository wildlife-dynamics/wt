# Design Decisions

This document explains the design decisions behind the wt-* framework's
architecture. It is aimed at contributors and advanced users who want to
understand *why* the system is structured the way it is, not just *what* the
pieces do (for that, see [Concepts](concepts.md)).

## Why a monorepo of separate packages?

The wt framework is split into 9 packages (6 core + 3 GCP metapackages) rather
than shipped as a single library. This is not accidental -- it reflects two
hard constraints and one soft one:

**Hard constraint: dependency isolation.** The compiler needs to reason about
tasks defined in third-party libraries, but it must never import those
libraries directly. A task library might depend on GDAL, TensorFlow, or any
number of heavy native dependencies. If the compiler imported task code to
inspect it, every machine running the compiler would need those dependencies
installed. Separate packages let the compiler operate with only its own
lightweight dependencies (Jinja2, py-rattler, Pydantic) while discovering
tasks through an out-of-process mechanism (more on this below).

**Hard constraint: different deployment targets.** The runner is a FastAPI web
server deployed on a cloud VM. The compiler is a build-time CLI tool that runs
on developer machines or in CI. Tasks execute inside ephemeral containers on
Cloud Batch. These three contexts have fundamentally different dependency
requirements. Forcing them into a single package would mean every deployment
carries unnecessary (and potentially conflicting) dependencies.

**Soft constraint: independent versioning.** Separate packages can be versioned
and released independently. A bug fix to the task decorator does not require
re-releasing the compiler. Each package uses `setuptools-scm` with per-package
tag patterns (e.g., `wt-registry/v0.1.0`, `wt-compiler/v0.2.0`), so version
numbers reflect actual changes in that package.

The monorepo structure (all packages in one Git repository) keeps the
development experience coherent. Cross-package changes can be made in a single
PR, CI runs tests across all packages, and `uv` workspace overrides let
developers use local editable installs during development.

## Package dependency graph

All core packages depend on **wt-contracts**, and nothing else depends on
everything. The graph is intentionally shallow and acyclic:

```
wt-contracts
    |
    +-- wt-registry
    |
    +-- wt-task
    |
    +-- wt-compiler  (also depends on py-rattler, Jinja2)
    |
    +-- wt-invokers  (also depends on py-rattler)
    |
    +-- wt-runner    (also depends on wt-invokers, FastAPI)
```

The key observation is that **wt-compiler does not depend on wt-registry, wt-task,
or any task library**. It depends only on wt-contracts (for Pydantic models that
define the shape of registry output) and communicates with wt-registry through
a subprocess call. This is the architectural boundary that makes dependency
isolation possible.

Similarly, **wt-runner depends on wt-invokers but not on wt-compiler**. The
runner receives pre-compiled workflow artifacts and executes them; it does not
need to know how they were built.

### wt-contracts as the foundation

wt-contracts is deliberately minimal. It contains only Pydantic models and a
Python Protocol -- no business logic, no CLI, no I/O. Its sole dependency is
Pydantic itself. This makes it cheap for every other package to depend on, and
changes to it are rare and intentional.

The contracts it defines fall into three categories:

- **Registry contracts** (`RegistryMetadata`, `RegistryEntry`, `RegistryOutput`):
  the JSON schema that wt-registry CLI produces and wt-compiler consumes.
- **Task protocol** (`TaskProtocol`): a `typing.Protocol` specifying the methods
  that task wrappers must implement (`.call()`, `.map()`, `.partial()`, etc.).
  The compiler generates code that calls these methods, and wt-task provides
  the concrete implementation.
- **CLI contracts** (`WorkflowCLIArgs`, `WorkflowCLIEnv`): the standard
  arguments and environment variables that generated workflow scripts accept
  and that invokers construct.

Each of these contracts defines a serialization boundary between packages.
Packages on either side of a boundary can evolve independently as long as they
respect the shared schema.

## Subprocess-based discovery

When the compiler needs to know what tasks are available in a set of
third-party libraries, it does not `import` those libraries. Instead, it:

1. Creates an ephemeral conda environment using py-rattler (solve + install)
2. Locates the `wt-registry` executable in that environment
3. Calls `wt-registry --format json --package <module>` as a subprocess
4. Parses the JSON output using the `RegistryOutput` Pydantic model from
   wt-contracts

This happens in `wt_compiler.discovery.discover_tasks_from_requirements`.

### Why not direct imports?

The alternative -- importing task modules into the compiler process to inspect
them -- would create several problems:

**Dependency explosion.** Each task library brings its own transitive
dependencies. A geospatial task library might need GDAL, rasterio, and
shapely. A machine-learning task library might need PyTorch. The compiler
would need all of these installed, which is impractical (some are
platform-specific, some conflict with each other, and the combined environment
would be enormous).

**Import side effects.** Python modules can execute arbitrary code at import
time. A task module might initialize database connections, configure logging,
or download model weights. The compiler should not trigger any of these side
effects -- it only needs metadata about the functions.

**Version conflicts.** Different task libraries might depend on incompatible
versions of the same package. In a single process, only one version can be
loaded. The subprocess approach lets each discovery happen in its own isolated
environment.

### How it works in practice

The `wt-registry` package provides both a decorator (`@register`) and a CLI
(`wt-registry`). Task library authors decorate their functions:

```python
from wt_registry import register

@register(title="Calculate NDVI", description="...", tags=["io"])
def calculate_ndvi(raster_path: str, band_red: int, band_nir: int) -> str:
    ...
```

When the CLI is invoked with `--package my_tasks`, it imports the specified
module (which triggers the `@register` decorators), then serializes the
collected registry to JSON. The output conforms to the `RegistryOutput` schema
from wt-contracts, which includes each function's metadata, import path, and
a JSON schema derived from its type annotations.

The compiler receives this JSON, validates it with Pydantic, and has everything
it needs to generate import statements and validate parameter schemas -- without
ever having imported the task code itself.

## Serialization boundaries

The framework has three main serialization boundaries where data crosses
package lines. At each boundary, Pydantic models and JSON schemas provide the
contract.

### Registry boundary (wt-registry to wt-compiler)

```
wt-registry CLI  --(JSON)--> wt-compiler
                    |
                    v
            RegistryOutput (Pydantic model in wt-contracts)
              +-- entries: dict[str, RegistryEntry]
                    +-- metadata: RegistryMetadata
                    +-- json_schema: dict (JSON Schema for parameters)
                    +-- public_module_path: str
                    +-- function_name: str
```

The registry CLI outputs JSON. The compiler validates it with
`RegistryOutput.model_validate_json()`. If the schema ever changes, both sides
can detect incompatibility at validation time rather than encountering subtle
runtime errors.

### CLI boundary (wt-invokers to generated workflows)

Generated workflows are standalone Python packages with a CLI entry point.
Invokers execute these workflows by constructing command-line arguments and
environment variables defined by `WorkflowCLIArgs` and `WorkflowCLIEnv` from
wt-contracts. This means invokers never import workflow code -- they
communicate through the process boundary.

### Task execution boundary (generated code to wt-task)

The compiler generates Python code that calls methods on task objects:

```python
result = task(my_function).partial(x=1).call()
results = task(my_function).map("input_file", file_list)
```

The generated code depends on the `TaskProtocol` interface defined in
wt-contracts. The concrete `task()` decorator and `SyncTask`/`AsyncTask`
classes live in wt-task. This separation means the compiler can generate code
without depending on wt-task -- it only needs to know the method signatures,
which are defined in wt-contracts.

## The compilation model

Workflows in the wt framework are **compiled** rather than interpreted. The
compiler reads a declarative YAML specification and produces a complete,
self-contained Python package. This is a deliberate choice with specific
tradeoffs.

### What the compiler produces

Given a `spec.yaml`, the compiler generates:

- **DAG module** (`dags/`): Python code that wires tasks together in the
  correct execution order, calling `.partial()`, `.call()`, `.map()`, and
  `.validate()` on task objects
- **Parameter schemas**: JSON Schema files describing the workflow's input
  parameters, derived from the task-level schemas discovered via the registry
- **Package scaffolding**: A `pyproject.toml` (via Jinja2 templates),
  Dockerfile, and pixi configuration so the workflow can be built and deployed
  as an independent conda/pip package
- **Dependency graph visualization**: A rendered graph (via pydot) showing
  task dependencies

The output is a **static Python package** that can be installed, version-pinned,
and deployed without the compiler present.

### Why compile rather than interpret?

An alternative design would be to have the runner parse `spec.yaml` at request
time and dynamically construct the execution graph. Compilation offers several
advantages:

**Reproducibility.** A compiled workflow is a snapshot. Its dependencies are
pinned, its code is generated, and its behavior does not change if upstream
task libraries release new versions. Two runs of the same compiled workflow
produce the same results (assuming deterministic tasks).

**Validation at build time.** The compiler validates parameter schemas, checks
for missing tasks, and verifies the DAG is acyclic before any code runs. Errors
surface during CI, not during a production workflow execution.

**No compiler at runtime.** The runner and invokers do not need the compiler
installed. The compiled workflow is a standalone package with only the
dependencies it actually uses (wt-task plus whatever task libraries it
references). This keeps the runtime environment minimal.

**Auditability.** The generated Python code is human-readable. You can inspect
exactly what a workflow does, what parameters it accepts, and what order tasks
execute in. There is no opaque interpreter layer.

### The fingerprinting mechanism

The compiler produces a content hash (fingerprint) of each workflow's
functional structure. This hash ignores cosmetic changes (titles, descriptions,
defaults) and captures only the structural schema -- which tasks are called,
what parameters they accept, and how they connect. If a workflow's fingerprint
has not changed, the compiled output can be reused without re-running the
compiler.

## GCP metapackages

Three of the nine packages are "metapackages" that contain no code of their
own:

| Metapackage | Bundles |
|-------------|---------|
| wt-task-gcp | wt-task + OpenTelemetry tracing |
| wt-invokers-gcp | wt-invokers + Google Cloud Batch + google-auth |
| wt-runner-gcp | wt-runner + wt-invokers-gcp + Pub/Sub + tracing |

Each has an empty `__init__.py` and a `pyproject.toml` that declares
dependencies. They exist because of a packaging ecosystem mismatch:

**pip/uv supports optional extras** -- you can write `pip install wt-invokers[gcp]`
and get the GCP dependencies. The core packages define these extras in their
`pyproject.toml` under `[project.optional-dependencies]`.

**conda does not support extras.** In the conda ecosystem (used via pixi for
building and distributing packages), each variant needs its own package name
and its own `pyproject.toml`. So `wt-invokers-gcp` exists as a separate conda
package that depends on `wt-invokers` plus the GCP libraries.

This means there are two equivalent ways to install a package with GCP support:

```bash
# Using pip/uv extras (single package with optional deps)
pip install wt-invokers[gcp]

# Using the metapackage (separate package, works with conda)
pip install wt-invokers-gcp    # or: pixi add wt-invokers-gcp
```

Both resolve to the same set of installed libraries. The metapackages are a
pragmatic bridge between pip's extras mechanism and conda's flat package model.

### Why not just use pip extras everywhere?

The wt framework uses pixi (which builds on conda) for environment management
and package distribution, particularly for packages with compiled native
dependencies (GDAL, rasterio, etc.) that are notoriously difficult to install
via pip. Since conda is a first-class distribution channel, conda-compatible
packaging is a requirement, not an afterthought. The metapackages are the
minimal solution that keeps both pip and conda users well-served without
duplicating any actual code.
