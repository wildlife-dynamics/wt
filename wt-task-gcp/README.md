# wt-task-gcp

Conda metapackage that bundles [wt-task](../wt-task/README.md) with GCP tracing dependencies.

## What it provides

- All of `wt-task` (task decorator, execution framework)
- OpenTelemetry tracing with GCP Cloud Trace exporter (`opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-gcp-trace`)

## Installation

### Conda (deployment)

```bash
pixi add wt-task-gcp
```

### pip (development)

For development, use the `tracing` extra on `wt-task` directly:

```bash
pip install wt-task[tracing]
```

## See also

- [wt-task README](../wt-task/README.md) for full documentation
