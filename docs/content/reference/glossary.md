# Glossary

Key terms used throughout the wt documentation.

| Term | Definition |
|------|------------|
| **Task** | A runtime wrapper created dynamically by the compiler from a registered function. Tasks are instances of `wt_task.SyncTask` and provide `.call()`, `.map()`, `.partial()`, `.validate()`, and `.skipif()` methods used in the compiled DAG code. Developers do not create tasks directly — they register functions with `@register`, and the compiler generates the corresponding `task(...)` calls. (In the legacy API, which is no longer supported, function registry authors used `@task` directly.) |
| **Task instance** | A specific invocation of a task within a workflow, identified by its `id` in the `spec.yaml`. The same registered function can appear as multiple task instances with different parameters. |
| **Registered function** | A Python function decorated with `@register` from wt-registry. Registration makes the function discoverable by the compiler and generates a JSON schema from its type annotations. |
| **Registry** | The global, in-process collection of all registered functions. Populated at import time by `@register` decorators. Accessed via `get_registry()` or the `wt-registry` CLI. |
| **spec.yaml** | A YAML file that declaratively defines a workflow: its ID, package requirements, and an ordered list of task instances with their data flow. Input to the compiler. |
| **DAG** | Directed acyclic graph. The execution graph formed by task instances and their data dependencies. Tasks flow forward; cycles are not allowed. |
| **Compilation** | The process of transforming a `spec.yaml` into a standalone Python package. Performed by `wt-compiler`. Includes dependency resolution, task discovery, validation, and code generation. |
| **Compiled workflow** | The output of compilation: a self-contained directory with generated DAG code, parameter schemas, a `pixi.toml`, Dockerfile, and tests. Executable via `pixi run` or wt-runner. |
| **Invoker** | An execution backend that runs a compiled workflow. Implementations include `LocalSubprocessInvoker` (runs via `pixi run` locally) and `CloudBatchInvoker` (dispatches to Google Cloud Batch). |
| **Runner** | The `wt-runner` FastAPI server that accepts workflow parameters over HTTP and dispatches execution to an invoker. |
| **partial** | A `spec.yaml` construct that binds keyword arguments to a task instance — either literal values or `${{ }}` references to other task outputs. |
| **map** | A `spec.yaml` construct that fans a task out over an iterable, invoking it once per element. Produces a list of results. |
| **mapvalues** | A `spec.yaml` construct that fans a task out over key-value pairs, preserving the keys. The input must be dict-like; the output is a dict with the same keys. |
| **Metapackage** | A dependency-only package (empty `__init__.py`) that bundles a core wt package with GCP-specific dependencies. Exists because conda does not support pip-style extras. |
