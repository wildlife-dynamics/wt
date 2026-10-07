"""Derivation hashing: a step's identity, and the per-run state it reads.

A step is keyed by what *produced* it — its code, its literal and runtime
arguments, and the identities of the steps feeding it — rather than by hashing
the input values themselves. That is what makes a warm run cheap: it never has
to decode and re-hash an intermediate it is not going to use.
"""

from __future__ import annotations

import contextlib
import functools
import importlib.metadata
import os
from contextvars import ContextVar
from typing import TYPE_CHECKING

from ._codec import json_digest

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from ._spec import CacheSpec

EPOCH_ENV_VAR = "WT_CACHE_EPOCH"
SCOPE_ENV_VAR = "WT_CACHE_SCOPE"

# task-instance id -> the identity downstream steps should fold in, or None when
# that step could not be cached. Absent and None mean the same thing to a reader.
_RUN_IDS: ContextVar[dict[str, str | None]] = ContextVar("_RUN_IDS")


@contextlib.contextmanager
def run_scope() -> Iterator[dict[str, str | None]]:
    """Scope a fresh identity table to one DAG execution.

    Entered once at DAG entry. Identities must not leak between runs: the same
    task-instance id means different things in different workflows.

    Examples:
        >>> with run_scope() as ids:
        ...     record("a", "sha256:deadbeef")
        ...     ids["a"]
        'sha256:deadbeef'
    """
    token = _RUN_IDS.set({})
    try:
        yield _RUN_IDS.get()
    finally:
        _RUN_IDS.reset(token)


def record(task_instance_id: str, identity: str | None) -> None:
    """Record what `task_instance_id` contributes to its dependents' keys.

    A no-op outside a `run_scope`, so a task called directly in a test or a REPL
    behaves exactly as it does today.
    """
    ids = _RUN_IDS.get(None)
    if ids is not None:
        ids[task_instance_id] = identity


def _upstream(task_instance_id: str) -> str | None:
    ids = _RUN_IDS.get(None)
    if ids is None:
        return None
    return ids.get(task_instance_id)


@functools.lru_cache(maxsize=1)
def _packages_distributions() -> Mapping[str, list[str]]:
    return importlib.metadata.packages_distributions()


@functools.cache
def distribution_version(anchor: str) -> str | None:
    """Return a version string for the distribution providing `anchor`, else None.

    None means "do not cache this step". Failing closed is the point: without a
    version, a code change would not move the key and the cache would serve the
    old result indefinitely. A module can map to more than one distribution, so
    all of them are folded in, sorted for stability.
    """
    top_level = anchor.split(".")[0]
    dists = _packages_distributions().get(top_level)
    if not dists:
        return None
    try:
        return ";".join(f"{d}=={importlib.metadata.version(d)}" for d in sorted(set(dists)))
    except importlib.metadata.PackageNotFoundError:
        return None


def task_identity(spec: CacheSpec) -> str | None:
    """Identify the code a step runs, or None if it cannot be pinned.

    `WT_CACHE_EPOCH` is the manual invalidator. A distribution version only moves
    on release and development happens against editable installs, so in those
    settings the epoch — an image digest on deploy — is what actually separates
    one build from another.
    """
    version = distribution_version(spec.anchor)
    if version is None:
        return None
    epoch = os.environ.get(EPOCH_ENV_VAR, "")
    return f"{spec.anchor}.{spec.function}@{version}#{spec.recipe}#{epoch}"


def step_identity(spec: CacheSpec) -> str | None:
    """Compute this step's cache key, or None if it cannot be cached.

    Returns None when the code cannot be pinned, or when any upstream step was
    itself uncacheable — uncacheability propagates down the DAG, because a key
    that omits an unknown input would collide across genuinely different runs.
    """
    task = task_identity(spec)
    if task is None:
        return None

    inputs: dict[str, list[str]] = {}
    for argname, dep_ids in spec.deps.items():
        resolved = [_upstream(dep_id) for dep_id in dep_ids]
        if any(identity is None for identity in resolved):
            return None
        inputs[argname] = [identity for identity in resolved if identity is not None]

    return "sha256:" + json_digest(
        {
            "task": task,
            "static": spec.static,
            "env": dict(spec.env),
            "params": dict(spec.params),
            "inputs": inputs,
            # Credentials reach tasks as environment variables keyed by connection
            # *name*, so byte-identical params can address different tenants. The
            # deployer sets this; wt-task cannot know the right granularity.
            "scope": os.environ.get(SCOPE_ENV_VAR, ""),
        }
    )
