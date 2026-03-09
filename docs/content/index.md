# Workflow Toolkit (`wt`)

Workflow Toolkit (`wt` for short) is a modular collection of Python packages
comprising a compiler, a task framework, and execution backends that together
allow you to build reproducible, webform-configurable workflows with native
access to the scientific software ecosystem. Key design goals:

- **No-code web forms for workflow templates.** Configure and launch workflows
  through auto-generated forms in the browser. Developers define the templates;
  the compiler handles the rest.

- **Conda-native, pixi-driven.** Compiled workflows are pixi projects.
  Dependencies resolve through conda channels and PyPI sources, so the full
  scientific stack — GDAL, R, PyTorch, system libraries — is natively
  supported alongside standard Python packages.

- **Fan-out over collections.** `map` and `mapvalues` distribute work across
  items. Execution strategy is configurable per workflow — sequential today,
  with concurrent backends on the roadmap.

- **Multiple execution backends.** Run locally via CLI. On the cloud, trigger
  workflows through a REST API or Pub/Sub — lightweight jobs run as local
  server processes, heavy jobs with custom hardware run on Cloud Batch.

- **Compile, don't interpret.** Compiled DAGs are plain Python you can read,
  diff, and version-control. No opaque runtime interpreter — what you see in
  the generated code is what runs.

---

To understand the model, start with [Concepts](concepts.md). To build a
workflow hands-on, go to [Getting Started](getting-started.md).

---

## Contributing

### Serving the docs locally

```bash
cd docs
uv run mkdocs serve
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).
