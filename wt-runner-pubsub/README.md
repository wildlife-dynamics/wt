# wt-runner-pubsub

Conda metapackage that bundles [wt-runner](../wt-runner/README.md) with [ecoscope-eda-core](https://github.com/wildlife-dynamics/ecoscope-eda-core) for Pub/Sub support.

## What it provides

- All of `wt-runner` (workflow execution, result retrieval, metadata endpoints)
- Pub/Sub endpoint (`/run-from-pubsub`) via `ecoscope-eda-core` message types

## Installation

### Conda (deployment)

```bash
pixi add wt-runner-pubsub
```

### pip (development)

For development, use the `pubsub` extra on `wt-runner` directly:

```bash
pip install wt-runner[pubsub]
```

### Compiled workflows

To emit `wt-runner-pubsub` as a dependency in compiled workflows:

```bash
wt-compiler compile --spec spec.yaml --runner-variant pubsub
```

## See also

- [wt-runner README](../wt-runner/README.md) for full documentation
