# Package Tasks for Distribution

This guide covers how to package your registered task functions so the compiler
can discover them and compiled workflows can depend on them at runtime.

---

## Why packaging matters

The compiler discovers tasks by installing packages into an ephemeral
environment and running `wt-registry` as a subprocess. A standalone `.py` file
is not enough — your tasks must live in an installable package. At runtime, the
compiled workflow (a pixi project) also depends on your task package.

---

## Minimal pyproject.toml

Every task package needs a `pyproject.toml`. Here is the minimal setup:

```toml
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[project]
name = "my-tasks"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "wt-registry",
    "wt-task",
]

[tool.setuptools.packages.find]
where = ["src"]
```

Use the `src` layout:

```
my-tasks/
├── pyproject.toml
└── src/
    └── my_tasks/
        ├── __init__.py
        └── tasks.py
```

!!! tip
    Re-export your task functions in `__init__.py` so the compiler can import
    them with a clean path (e.g. `from my_tasks import generate_numbers`).

---

## Testing registration locally

After installing your package (`pip install -e ./my-tasks`), verify that the
registry can see your tasks:

```bash
wt-registry --package my_tasks --format pretty
```

If your functions appear with correct titles, types, and schemas, you are ready
to reference them in a `spec.yaml`.

---

## Publishing to PyPI

Standard Python packaging workflow:

```bash
# Build
uv build ./my-tasks

# Upload to PyPI (or a private index)
uv publish ./my-tasks/dist/*
```

PyPI packages work for local development with `pip install` / `uv pip install`.
However, the compiler's `requirements:` section currently resolves from
**conda channels only**, so PyPI-only packages require an additional step to be
usable in compiled workflows.

!!! note "Roadmap — PyPI support in requirements"
    Support for
    [pypi-dependencies](https://pixi.sh/latest/reference/pixi_manifest/#pypi-dependencies)
    in the `requirements:` section is planned. This will enable direct use of
    PyPI packages without building conda packages.

---

## Building conda packages

For the compiler to resolve your task package from `requirements:`, it must be
available on a conda channel. The simplest approach for local development is a
**file-based conda channel**.

### Using rattler-build

```bash
# Install rattler-build
pixi global install rattler-build

# Create a recipe (recipe.yaml)
# Build the package
rattler-build build --recipe recipe.yaml

# The output goes to ./output/<platform>/
# Point the compiler to this directory as a local channel
```

### Using pixi for packaging

If your project already uses pixi, you can build conda packages directly from
your `pixi.toml` workspace.

### Hosting on a conda channel

For team or CI use, publish packages to a conda channel such as
[prefix.dev](https://prefix.dev) or a self-hosted channel. The compiler's
allowed channels are configured in the `CHANNELS` list — see the
[Tooling & Prerequisites](../concepts/tooling.md) page for details on
channel restrictions.

---

## Making tasks discoverable by the compiler

The compiler discovers tasks using this sequence:

1. Reads `requirements:` from your `spec.yaml`.
2. Creates an ephemeral conda environment with those packages.
3. Runs `wt-registry --package <import_name>` inside that environment.
4. Collects the JSON schema for every `@register`-decorated function.

For this to work:

- Your package must declare `wt-registry` as a dependency (so the CLI is
  available in the environment).
- Your tasks must be importable via the package name listed in `--package`
  (i.e. `import my_tasks` must trigger registration).
- Every task function must have complete type annotations.
