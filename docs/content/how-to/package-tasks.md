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

## Publishing to pip-compatible locations

Task packages can be published to any pip-compatible location — PyPI, a private
index, a GitHub repository, or a local filesystem path. However, the compiler's
`requirements:` section currently resolves from **conda channels only**, so
pip-based sources are not yet supported in compiled workflows.

!!! note "Roadmap — pip source support in requirements"
    Support for pip-compatible package sources (PyPI, GitHub, local paths) in the
    `requirements:` section is forthcoming. This will enable direct use of
    packages from these locations without building conda packages.

---

## Building conda packages

For the compiler to resolve your task package from `requirements:`, it must be
available on a conda channel. The simplest approach for local development is a
**local file-based conda channel** built with `pixi build`.

### Using pixi build

`pixi build` is the recommended way to build conda packages from your project:

```bash
# Build a conda package from your pixi project
pixi build
```

This produces a local conda package that the compiler can resolve. Point the
compiler to the output directory as a local channel.

### Hosting on a remote conda channel

!!! warning "Under development"
    Remote conda channel hosting (e.g. [prefix.dev](https://prefix.dev) or
    self-hosted channels) is an area under active development and does not work
    today. For now, use a local file-based channel produced by `pixi build`.

---

## Making tasks discoverable by the compiler

The compiler discovers tasks using this sequence:

1. Reads `requirements:` from your `spec.yaml`.
2. Creates an ephemeral conda environment with those packages.
3. Runs `wt-registry --package <import_name>` inside that environment.
4. Collects the JSON schema for every `@register`-decorated function.

To recap, the key requirements covered in this guide are:

- Your package must declare `wt-registry` as a dependency (so the CLI is
  available in the environment).
- Your tasks must be importable via the package name listed in `--package`
  (i.e. `import my_tasks` must trigger registration).
- Every task function must have complete type annotations.

For more on this discovery mechanism, see
[Core Concepts](../concepts/index.md). For the full `spec.yaml` syntax, see
the [`spec.yaml` reference](../reference/spec-yaml.md).
