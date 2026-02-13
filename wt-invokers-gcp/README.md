# wt-invokers-gcp

Conda metapackage that bundles [wt-invokers](../wt-invokers/README.md) with GCP dependencies for Cloud Batch execution.

## What it provides

- All of `wt-invokers` (abstract invoker interface, local subprocess invokers)
- GCP dependencies for `CloudBatchInvoker` (`google-cloud-batch`, `google-auth`)

## Installation

### Conda (deployment)

```bash
pixi add wt-invokers-gcp
```

### pip (development)

For development, use the `gcp` extra on `wt-invokers` directly:

```bash
pip install wt-invokers[gcp]
```

## See also

- [wt-invokers README](../wt-invokers/README.md) for full documentation
