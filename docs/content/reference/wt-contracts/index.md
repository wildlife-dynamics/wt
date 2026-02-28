# wt-contracts

Shared interface contracts for the wt workflow ecosystem.

## Overview

`wt-contracts` is the **foundation package** of the wt monorepo. It provides Pydantic models and Python Protocols that define the type-safe interfaces used for inter-package communication. Every other wt package depends on `wt-contracts`.

The package contains three modules:

| Module | Purpose |
|--------|---------|
| [`registry`](registry-models.md) | Pydantic models for registry CLI output (`RegistryMetadata`, `RegistryEntry`, `RegistryOutput`) |
| [`task`](task-models.md) | Protocol defining the task execution interface (`TaskProtocol`) |
| [`cli`](cli-models.md) | Standard CLI argument and environment variable contracts (`WorkflowCLIArgs`, `WorkflowCLIEnv`) |

## Role in the Architecture

`wt-contracts` enables **subprocess-based communication** between packages. Rather than importing each other directly (which would create dependency conflicts), packages serialize data through these shared schemas:

- **wt-registry** populates `RegistryEntry` and `RegistryOutput` models, then serializes them as JSON via its CLI.
- **wt-compiler** parses that JSON output and validates it against the same `RegistryOutput` schema.
- **wt-task** implements the `TaskProtocol`, and **wt-compiler** generates code that calls `TaskProtocol` methods.
- **wt-invokers** constructs `WorkflowCLIArgs` and `WorkflowCLIEnv` when launching workflow subprocesses.

```
wt-contracts (Pydantic models + Protocols)
    |
    +---> wt-registry (produces RegistryOutput JSON)
    +---> wt-compiler (consumes RegistryOutput JSON, generates TaskProtocol calls)
    +---> wt-task     (implements TaskProtocol)
    +---> wt-invokers (uses WorkflowCLIArgs / WorkflowCLIEnv)
    +---> wt-runner   (uses WorkflowCLIArgs / WorkflowCLIEnv)
```

## Installation

```bash
pip install wt-contracts
```

Or with uv:

```bash
uv add wt-contracts
```

### Requirements

- Python >= 3.10
- Pydantic >= 2.0.0, < 3.0.0

## Public API

All public symbols are re-exported from the top-level package:

```python
from wt_contracts import (
    # Registry contracts
    RegistryMetadata,
    RegistryEntry,
    RegistryOutput,
    # Task protocol
    TaskProtocol,
    # CLI contracts
    WorkflowCLIArgs,
    WorkflowCLIEnv,
)
```

## Versioning

`wt-contracts` uses `setuptools-scm` for versioning. Versions are derived from git tags matching the pattern `wt-contracts/v<version>`.
