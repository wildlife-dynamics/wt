# Workflow Toolkit (`wt`)

Workflow Toolkit (`wt` for short) lets you **register** Python functions as
reusable tasks, **specify** how they connect in a YAML file, **compile** the
spec into a standalone, reproducible package, and **run** it locally or in the
cloud — with auto-generated web forms for configuration.

- **Type-driven registration.** Decorate functions with `@register` — type
  annotations generate JSON schemas that power web forms and compile-time
  validation.

- **Declarative YAML specs.** Wire tasks together with `partial`, `map`,
  `mapvalues`, and `skipif` — no Python glue code required.

- **Compile, don't interpret.** The compiler outputs a standalone pixi project
  with plain Python DAG code you can read, diff, and version-control.

- **Conda-native, fully reproducible.** Dependencies resolve through conda
  channels and PyPI, so the full scientific stack (GDAL, R, PyTorch) is
  natively supported. Every version is pinned.

- **Run anywhere.** Execute locally via CLI, through a REST API, or on Google
  Cloud Batch.

- **No-code web forms.** Auto-generated browser forms let non-developers
  configure and launch workflows without touching code.

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
