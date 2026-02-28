# Workflow Toolkit (`wt`)

A modular framework for compiling and executing typed Python workflows.
The wt-* monorepo provides 9 packages (6 core + 3 GCP metapackages) that
together handle task registration, workflow compilation, and execution
across local and cloud backends.

For a high-level view of how the packages fit together, see the
[Architecture](reference/packages.md) section.

---

## Where do I begin?

### I want to build a workflow

Start with the tutorials — they walk you through creating tasks and wiring
them into a compiled workflow from scratch.

1. [Registering Tasks](tutorials/registering-tasks.md) — write typed Python
   functions and register them for discovery.
2. [Building Your First Workflow](tutorials/first-workflow.md) — create a
   `spec.yaml`, compile it, and explore the output.

### I want to define or modify a `spec.yaml`

The [`spec.yaml` reference](reference/spec-yaml.md) documents
every field in the spec format: task instances, variable references, map/mapvalues,
task groups, skipif, and RJSF overrides.

### I want to compile and run a workflow

The [Compile a Workflow](how-to/compile-workflow.md) how-to guide covers
CLI usage, compilation options, and troubleshooting.

### I want to understand how things work under the hood

The [Architecture](explanation/architecture.md) section covers the
monorepo design, subprocess-based task discovery, serialization boundaries,
and why workflows are compiled to static Python code.

### I need API details for a specific package

Each package has its own reference section:

| Package | What it does |
|---------|-------------|
| [wt-contracts](reference/wt-contracts/index.md) | Shared Pydantic models and protocols |
| [wt-registry](reference/wt-registry/index.md) | `@register` decorator and function discovery |
| [wt-task](reference/wt-task/index.md) | `@task` decorator with `.call()`, `.map()`, `.partial()` |
| [wt-compiler](reference/wt-compiler/index.md) | Workflow YAML to executable DAG compilation |
| [wt-invokers](reference/wt-invokers/index.md) | Execution backends (local subprocess, Cloud Batch) |
| [wt-runner](reference/wt-runner/index.md) | FastAPI server for workflow execution |

---

## Contributing

### Serving the docs locally

```bash
cd docs
uv run mkdocs serve
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).
