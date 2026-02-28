# Package Architecture

The wt-* monorepo contains 9 packages: 6 core packages and 3 GCP metapackages.
For the rationale behind these design choices, see
[Design Decisions](../explanation/architecture.md).

## Core Packages

| Package | Purpose | Key Modules | CLI |
|---------|---------|-------------|-----|
| **wt-contracts** | Shared Pydantic models for inter-package compatibility | `registry.py`, `task.py`, `cli.py` | — |
| **wt-registry** | `@register` decorator for function discovery with JSON schema generation | `decorator.py`, `registry.py`, `validation.py` | `wt-registry` |
| **wt-task** | `@task` decorator with `.call()`, `.map()`, `.partial()`, `.validate()` methods | `decorator.py`, `base.py`, `sync_task.py`, `async_task.py` | — |
| **wt-compiler** | Compiles workflow YAML specs into executable DAG artifacts | `compiler.py`, `spec.py`, `discovery.py`, `templates/` | `wt-compiler` |
| **wt-invokers** | Abstract invoker interface + implementations (local subprocess, Cloud Batch) | `abstract.py`, `local.py`, `cloud_batch.py` | — |
| **wt-runner** | FastAPI server for workflow execution with multi-backend support | `app.py`, `tracing.py` | uvicorn |

## GCP Metapackages

These are dependency-only metapackages (empty `__init__.py`) that bundle a core package with its GCP-specific dependencies for convenient installation.

| Metapackage | Bundles | GCP Dependencies |
|-------------|---------|------------------|
| **wt-task-gcp** | wt-task | `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-gcp-trace` |
| **wt-invokers-gcp** | wt-invokers | `google-cloud-batch`, `google-auth` |
| **wt-runner-gcp** | wt-runner + wt-invokers-gcp | `opentelemetry-sdk`, `opentelemetry-exporter-gcp-trace`, `gcloud-aio-pubsub`, `ecoscope-eda-core` |

The core packages also expose the same GCP dependencies as optional extras (e.g., `pip install wt-invokers[gcp]`). The metapackages exist primarily because conda does not support extras/optional-dependencies, so each variant needs its own package definition.

## Directory Layout

Each core package follows this structure:

```
<package-name>/            # e.g., wt-registry/
├── src/<package_name>/    # Source code (underscores)
│   ├── __init__.py
│   └── *.py
├── tests/                 # Unit tests (test_*.py)
├── pyproject.toml
└── README.md
```

GCP metapackages are minimal:

```
<package-name>-gcp/        # e.g., wt-invokers-gcp/
├── src/<package_name>_gcp/
│   └── __init__.py        # Empty (dependency-only)
├── pyproject.toml
└── README.md
```

## Key Design Decisions

- **Subprocess-based discovery**: wt-compiler discovers tasks via the `wt-registry` CLI (no direct imports), avoiding dependency conflicts.
- **No circular dependencies**: wt-contracts is the foundation; all other packages depend on it.
- **Pydantic v2**: All packages use Pydantic for data validation and JSON schema generation.
