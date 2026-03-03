# Workflow Toolkit (`wt`)

!!! tip "New to `wt`?"
    Start with **[Core Concepts](concepts/index.md)** for a bird's-eye view
    of how workflows, specs, and compilation fit together.

Workflow Toolkit (`wt` for short) is a modular collection of Python packages
comprising a compiler, a task framework, and execution backends that together
allow you to build reproducible, webform-configurable workflows with native
access to the scientific software ecosystem. Key design goals:

- **No-code web forms for workflow templates.** Configure and launch workflows
  through auto-generated forms in the browser. Developers define the templates;
  the compiler handles the rest.

- **Conda-native, pixi-driven.** Compiled workflows are pixi projects.
  Dependencies resolve through conda channels, so the full scientific stack —
  GDAL, R, PyTorch, system libraries — is natively supported.

- **Fan-out over collections.** `map` and `mapvalues` distribute work across
  items. Execution strategy is configurable per workflow — sequential today,
  with concurrent backends on the roadmap.

- **Multiple execution backends.** Run locally via CLI. On the cloud, trigger
  workflows through a REST API or Pub/Sub — lightweight jobs run as local
  server processes, heavy jobs with custom hardware run on Cloud Batch.

- **Compile, don't interpret.** Compiled DAGs are plain Python you can read,
  diff, and version-control. No opaque runtime interpreter — what you see in
  the generated code is what runs.

## Quick navigation

| If you want to… | Go to |
|---|---|
| Build a workflow from scratch | [Tutorials](tutorials/registering-tasks.md) |
| Write or edit a `spec.yaml` | [`spec.yaml` reference](reference/spec-yaml.md) |
| Compile and run a workflow | [Compile a Workflow](how-to/compile-workflow.md) |
| Understand the architecture | [Design Decisions](explanation/architecture.md) |
| Look up a package API | [Reference](reference/wt-contracts/index.md) |

---

## Contributing

### Serving the docs locally

```bash
cd docs
uv run mkdocs serve
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).
