"""A step's cache key, and the per-run state it reads.

Every argument a step receives is content-exact in its key: literals through
`static`, environment reads through `env`, form values through `params`, and
upstream outputs through `deps`, as the digests their producers recorded. A
warm run stays cheap because those digests are read from run state rather than
recomputed from values the step is not going to decode.
"""

from __future__ import annotations

import contextlib
import functools
import importlib.metadata
import os
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ._codec import json_digest

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from ._spec import CacheSpec

EPOCH_ENV_VAR = "WT_CACHE_EPOCH"
SCOPE_ENV_VAR = "WT_CACHE_SCOPE"

Outcome = Literal["hit", "miss", "unservable", "refused", "uncacheable", "inert"]


@dataclass(frozen=True)
class CacheRecord:
    """What one step contributed to the run, and why.

    Attributes:
        digest: The content digest downstream steps fold into their keys, or
            None when this step could not be cached.
        outcome: What the cache did for this step.
        reason: Why, for the outcomes that are not self-explanatory.
    """

    digest: str | None
    outcome: Outcome
    reason: str | None = None


_RUN_IDS: ContextVar[dict[str, CacheRecord]] = ContextVar("_RUN_IDS")

# The generated CLI builds its result envelope after the DAG's scope has closed,
# so the last table outlives it. One run per process, so one slot is enough.
_LAST_RUN: dict[str, CacheRecord] = {}


@contextlib.contextmanager
def run_scope() -> Iterator[dict[str, CacheRecord]]:
    """Scope a fresh identity table to one DAG execution.

    Entered once at DAG entry. Identities must not leak between runs: the same
    task-instance id means different things in different workflows.

    Examples:
        >>> with run_scope() as ids:
        ...     record("a", "sha256:deadbeef", "miss")
        ...     ids["a"].digest
        'sha256:deadbeef'
    """
    table: dict[str, CacheRecord] = {}
    token = _RUN_IDS.set(table)
    try:
        yield table
    finally:
        _RUN_IDS.reset(token)
        _LAST_RUN.clear()
        _LAST_RUN.update(table)


def record(
    task_instance_id: str,
    identity: str | None,
    outcome: Outcome,
    reason: str | None = None,
) -> None:
    """Record what `task_instance_id` contributes to its dependents' keys.

    A no-op outside a `run_scope`, so a task called directly in a test or a REPL
    behaves exactly as it does today.
    """
    ids = _RUN_IDS.get(None)
    if ids is not None:
        ids[task_instance_id] = CacheRecord(identity, outcome, reason)


def run_report() -> dict[str, dict[str, str | None]]:
    """Per-step cache outcomes for this run, as JSON-able rows.

    The compile-time report is a claim about declared types; this is what
    actually happened — which steps were served, which refused, and why.

    Examples:
        >>> with run_scope():
        ...     record("a", None, "refused", "no union arm")
        ...     run_report()
        {'a': {'digest': None, 'outcome': 'refused', 'reason': 'no union arm'}}
    """
    ids = _RUN_IDS.get(None)
    table = ids if ids is not None else _LAST_RUN
    return {
        step: {"digest": row.digest, "outcome": row.outcome, "reason": row.reason}
        for step, row in table.items()
    }


def _upstream(task_instance_id: str) -> str | None:
    ids = _RUN_IDS.get(None)
    if ids is None:
        return None
    row = ids.get(task_instance_id)
    return row.digest if row is not None else None


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


def step_identity_with_reason(spec: CacheSpec) -> tuple[str | None, str | None]:
    """Compute this step's cache key, or None and the reason it has none."""
    task = task_identity(spec)
    if task is None:
        return None, f"no distribution version for {spec.anchor!r}"

    inputs: dict[str, list[str]] = {}
    for argname, dep_ids in spec.deps.items():
        resolved = []
        for dep_id in dep_ids:
            identity = _upstream(dep_id)
            if identity is None:
                return None, f"upstream {dep_id!r} uncacheable"
            resolved.append(identity)
        inputs[argname] = resolved

    key = {
        "task": task,
        "static": spec.static,
        "env": dict(spec.env),
        "params": dict(spec.params),
        "inputs": inputs,
    }
    if spec.scoped:
        # Only steps that read the world. Credentials reach tasks as env vars
        # keyed by connection name, so byte-identical params can address
        # different tenants; a derived step cannot be reached without already
        # holding the same input digests, so scoping it would only mean that a
        # fresh token costs a whole cold run instead of one source refetch.
        key["scope"] = os.environ.get(SCOPE_ENV_VAR, "")

    return "sha256:" + json_digest(key), None


def step_identity(spec: CacheSpec) -> str | None:
    """Compute this step's cache key, or None if it cannot be cached.

    Returns None when the code cannot be pinned, or when any upstream step was
    itself uncacheable — uncacheability propagates down the DAG, because a key
    that omits an unknown input would collide across genuinely different runs.
    """
    return step_identity_with_reason(spec)[0]
