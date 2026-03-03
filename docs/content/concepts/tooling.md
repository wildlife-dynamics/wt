# Tooling & Prerequisites

`wt` sits at the intersection of two packaging ecosystems — **PyPI** (pip/uv)
and **conda** (pixi/rattler). Both tools play a role; which one you reach for
depends on what you're doing.

---

## uv — Python package development

[uv](https://docs.astral.sh/uv/) is a fast Python package manager and project
tool. It's what we use to develop the `wt` framework packages themselves.

For task packages that are **pure Python** (no system library dependencies), uv
is a natural choice for local development: fast installs, editable mode, and
standard `pyproject.toml` workflows.

uv is sufficient for:

- Writing task code and running tests
- Running `wt-registry` locally to inspect registered functions
- Running `wt-compiler compile` to produce compiled workflow artifacts
- Installing and developing individual `wt` packages

---

## pixi — workflow execution and the conda ecosystem

[pixi](https://pixi.sh) is a cross-platform package manager built on the conda
ecosystem. Compiled workflows are **pixi projects** — the compiler outputs a
`pixi.toml`, and both execution backends (`LocalSubprocessInvoker`,
`CloudBatchInvoker`) invoke workflows via `pixi run`.

**pixi is required to run any compiled workflow end-to-end.**

pixi is the better choice when your task packages depend on non-Python
libraries (GDAL, R, system libs, etc.) — these resolve naturally through conda
channels but not through PyPI.

If you want a **single-tool experience**, pixi can handle everything uv does
(it supports
[pypi-dependencies](https://pixi.sh/latest/reference/pixi_manifest/#pypi-dependencies)),
so you can use pixi for development too.

---

## Task package distribution

Task registries must be **installable packages** — the compiler discovers them
by installing the packages listed in `requirements:` into an ephemeral
environment and running `wt-registry` as a subprocess. You cannot just write a
`.py` module and point the compiler at it; the code must be packaged.

### Packaging with uv/pip

Standard `pyproject.toml`, publish to PyPI or install locally. This is the most
expedient path for local development and pure-Python registries.

```toml
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[project]
name = "my-tasks"
version = "0.1.0"
dependencies = ["wt-registry", "wt-task"]
```

### Packaging as conda/rattler packages

The more stable choice when your registry depends on packages that are better
handled through conda (system binaries, compiled extensions, etc.). Conda
packages are resolved from conda channels and installed into the pixi
environment that the compiler creates.

### How `requirements:` resolves today

Currently, the `requirements:` section in `spec.yaml` resolves packages from
**conda channels only**. This means your task packages must be available as
conda packages (or installable from a conda channel) for the compiler to
discover them.

!!! tip "Roadmap — PyPI support in requirements"
    We plan to add support for
    [pypi-dependencies](https://pixi.sh/latest/reference/pixi_manifest/#pypi-dependencies)
    in the `requirements:` section. This will enable editable installs during
    development, simpler packaging workflows, and a more ergonomic dev loop —
    while conda channel support remains for packages that need it.

---

## Summary — which tool when?

| You want to... | Use |
|---|---|
| Develop a pure-Python task package | uv or pixi |
| Develop a task package with system deps | pixi |
| Run `wt-compiler compile` | uv or pixi |
| Run a compiled workflow | pixi (required) |
| Use one tool for everything | pixi |
