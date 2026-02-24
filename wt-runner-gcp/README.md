# wt-runner-gcp

Conda metapackage that bundles [wt-runner](../wt-runner/README.md) with all GCP dependencies for production deployment.

## What it provides

- All of `wt-runner` (workflow execution, result retrieval, metadata endpoints)
- Pub/Sub endpoint (`/run-from-pubsub`) via `ecoscope-eda-core` message types
- GCP Cloud Trace exporting via OpenTelemetry (`opentelemetry-sdk`, `opentelemetry-exporter-gcp-trace`)
- Pub/Sub client (`gcloud-aio-pubsub`)
- Cloud Batch invoker dependencies via `wt-invokers-gcp`
- GCP task tracing dependencies via `wt-task-gcp`

## Installation

### Conda (deployment)

```bash
pixi add wt-runner-gcp
```

### pip (development)

For development, use the `gcp` extra on `wt-runner` directly:

```bash
pip install wt-runner[gcp]
```

### Compiled workflows

To emit `wt-runner-gcp` as a dependency in compiled workflows:

```bash
wt-compiler compile --spec spec.yaml --variant gcp
```

## See also

- [wt-runner README](../wt-runner/README.md) for full documentation
