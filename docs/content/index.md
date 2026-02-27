# wt-* Workflow Framework

A monorepo providing a workflow compilation and execution framework across 9 packages (6 core + 3 GCP metapackages).

## Package Architecture

```
wt-contracts (foundation - shared type contracts)
    |
    +-> wt-registry (function registration & discovery)
    +-> wt-task (task execution framework)
    |       +-> wt-task-gcp (metapackage: + GCP tracing)
    +-> wt-compiler (workflow YAML -> executable DAG)
    +-> wt-invokers (execution backends)
    |       +-> wt-invokers-gcp (metapackage: + Cloud Batch deps)
    +-> wt-runner -> wt-invokers (FastAPI web server)
            +-> wt-runner-gcp (metapackage: + Pub/Sub, tracing, Cloud Batch)
                    +-> wt-invokers-gcp
```

## Quick Start

### Serving the docs locally

```bash
cd docs
uv run mkdocs serve
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Next Steps

- [Package Architecture](reference/packages.md) — overview of all 9 packages and their relationships.
