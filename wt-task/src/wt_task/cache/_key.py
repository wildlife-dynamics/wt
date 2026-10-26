"""A step's cache key, and the per-run state it reads.

Every argument a step receives is content-exact in its key: literals through
`fixed_inputs`, environment reads through `env`, form values through the
params `run_scope` was given, and upstream outputs through `upstream_inputs`,
as the digests their producers recorded. A warm run stays cheap because those
digests are read from run state rather than recomputed from values the step is
not going to decode.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import importlib.metadata
import os
import warnings
from collections import deque
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from wt_task.exceptions import TaskInstanceError

from ._codec import json_digest
from ._settings import CacheSettings, active_settings, load_settings, use_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ._spec import CacheSpec, ResolvedTask


Outcome = Literal["hit", "miss", "expired", "unservable", "refused", "uncacheable", "inert"]


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
# Per-step form values, as the DAG received them. Passed once at DAG entry
# rather than baked into every step's spec, and keyed on raw: what the step's
# wrapper ends up seeing may have been coerced by `validate`.
_RUN_PARAMS: ContextVar[dict[str, Any]] = ContextVar("_RUN_PARAMS")

# The generated CLI writes its cache report after the DAG's scope has closed,
# so the last table outlives it. One run per process, so one slot is enough.
_LAST_RUN: dict[str, CacheRecord] = {}


@dataclass
class _Exit:
    """How the last `run_scope` ended, for a report built after it closed.

    Strings rather than the exception itself, which would keep every frame of
    the failed run alive.
    """

    settings: CacheSettings | None = None
    error: str | None = None
    failed_step: str | None = None


_LAST_EXIT = _Exit()


def _failed_step(error: BaseException) -> str | None:
    """The task instance an error came from, if anything in its chain says."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, TaskInstanceError):
            return current.task_instance_id
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


@contextlib.contextmanager
def run_scope(
    params: dict[str, Any] | None = None,
    settings: CacheSettings | None = None,
) -> Iterator[dict[str, CacheRecord]]:
    """Scope a fresh identity table, this run's parameters and its settings.

    Entered once at DAG entry. Identities must not leak between runs: the same
    task-instance id means different things in different workflows, and the
    settings are read here once rather than per step.

    Args:
        params: The whole run's parameters, keyed by task-instance id, exactly
            as the DAG received them.
        settings: Explicit settings. Loaded from the environment and its file
            sources when omitted.

    Examples:
        >>> with run_scope() as ids:
        ...     record("a", "deadbeef", "miss")
        ...     ids["a"].digest
        'deadbeef'
    """
    table: dict[str, CacheRecord] = {}
    resolved = settings if settings is not None else load_settings()
    token = _RUN_IDS.set(table)
    params_token = _RUN_PARAMS.set(params or {})
    error: str | None = None
    failed_step: str | None = None
    try:
        with use_settings(resolved):
            yield table
    except Exception as e:
        error, failed_step = str(e) or type(e).__name__, _failed_step(e)
        raise
    finally:
        _RUN_IDS.reset(token)
        _RUN_PARAMS.reset(params_token)
        # Kept on failure too: what ran before the error is the useful part.
        _LAST_RUN.clear()
        _LAST_RUN.update(table)
        _LAST_EXIT.settings, _LAST_EXIT.error, _LAST_EXIT.failed_step = (
            resolved,
            error,
            failed_step,
        )


def step_params(task_instance_id: str) -> dict[str, Any]:
    """Return the parameters this run gave one step, or an empty dict.

    Examples:
        >>> with run_scope(params={"a": {"n": 1}}):
        ...     step_params("a")
        {'n': 1}
    """
    params = _RUN_PARAMS.get(None) or {}
    return params.get(task_instance_id) or {}


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


@dataclass(frozen=True)
class _Installed:
    """One distribution's metadata, read once."""

    version: str
    requires: tuple[str, ...]
    extras: tuple[str, ...]


@dataclass(frozen=True)
class _Unreadable:
    """A distribution whose metadata raised; looking it up re-raises."""

    error: Exception


@functools.cache
def _index() -> tuple[
    dict[str, _Installed | _Unreadable], tuple[tuple[importlib.metadata.Distribution, str], ...]
]:
    """Read every installed distribution's metadata in one pass.

    Per-name `importlib.metadata` calls rescan every path entry and re-parse
    METADATA each time, which across a few hundred distributions cost seconds
    per process. Returns the first distribution per PEP 503 name — the one a
    by-name lookup would find — plus every distribution with its `Name`, for
    the top-level module lookup.
    """
    by_name: dict[str, _Installed | _Unreadable] = {}
    every: list[tuple[importlib.metadata.Distribution, str]] = []
    for dist in importlib.metadata.distributions():
        try:
            meta = dist.metadata
            name = meta["Name"]
            if name is None:
                continue
            requires = meta.get_all("Requires-Dist")
            if requires is None and dist.read_text("requires.txt") is not None:
                requires = dist.requires  # egg-info, as `Distribution.requires` falls back
            entry: _Installed | _Unreadable = _Installed(
                meta["Version"], tuple(requires or ()), tuple(meta.get_all("Provides-Extra") or ())
            )
        except Exception as e:  # re-raised on lookup, which fails closed
            # The directory name is all we have left; without even that, no
            # lookup could find this distribution, so nothing can be trusted.
            stem: str | None = getattr(dist, "_normalized_name", None)
            if stem is None:
                raise
            name, entry = stem, _Unreadable(e)
        else:
            every.append((dist, name))
        by_name.setdefault(canonicalize_name(name), entry)
    return by_name, tuple(every)


def _installed(name: str) -> _Installed | None:
    """Indexed metadata of an installed distribution, or None if it is not installed."""
    entry = _index()[0].get(canonicalize_name(name))
    if isinstance(entry, _Unreadable):
        raise entry.error
    return entry


# Stdlib's own per-distribution halves of `packages_distributions`, from 3.11.
_TOP_LEVEL_DECLARED: Any = getattr(importlib.metadata, "_top_level_declared", None)
_TOP_LEVEL_INFERRED: Any = getattr(importlib.metadata, "_top_level_inferred", None)


class _TopLevel(Mapping[str, list[str]]):
    """`importlib.metadata.packages_distributions()`, computed one key at a time.

    The full mapping infers top-level names from `dist.files` for every
    distribution without a `top_level.txt`, which parses every RECORD. A
    distribution can only infer a name its RECORD text contains, so the others
    are skipped unparsed. Inference itself stays stdlib's, which differs by
    Python version; before 3.11 there is no per-distribution helper, and the
    full mapping is used.
    """

    def __init__(self) -> None:
        self._found: dict[str, list[str]] = {}

    @functools.cached_property
    def _full(self) -> Mapping[str, list[str]]:
        return importlib.metadata.packages_distributions()

    def __getitem__(self, top_level: str) -> list[str]:
        if _TOP_LEVEL_DECLARED is None or _TOP_LEVEL_INFERRED is None:
            return self._full[top_level]
        if top_level not in self._found:
            self._found[top_level] = [
                name for dist, name in _index()[1] if self._provides(dist, top_level)
            ]
        if not self._found[top_level]:
            raise KeyError(top_level)
        return self._found[top_level]

    def _provides(self, dist: importlib.metadata.Distribution, top_level: str) -> bool:
        declared = _TOP_LEVEL_DECLARED(dist)
        if declared:
            return top_level in declared
        record = dist.read_text("RECORD")
        if record and top_level not in record:
            return False
        return top_level in set(_TOP_LEVEL_INFERRED(dist))

    def __iter__(self) -> Iterator[str]:
        return iter(self._full)

    def __len__(self) -> int:
        return len(self._full)


@functools.lru_cache(maxsize=1)
def _packages_distributions() -> Mapping[str, list[str]]:
    return _TopLevel()


def _installed_version(name: str) -> str | None:
    """Version of an installed distribution, or None if it is not installed."""
    installed = _installed(name)
    return installed.version if installed is not None else None


@functools.cache
def _requirements(name: str) -> tuple[Requirement, ...]:
    """Parsed requirements of one distribution, skipping any it spells wrongly."""
    installed = _installed(name)
    parsed = []
    for raw in installed.requires if installed is not None else ():
        try:
            parsed.append(Requirement(raw))
        except InvalidRequirement:  # noqa: PERF203  # per-requirement isolation; lists are short
            continue
    return tuple(parsed)


def _extras(name: str) -> list[str]:
    installed = _installed(name)
    return list(installed.extras) if installed is not None else []


def _gating_extras(req: Requirement, extras: list[str]) -> list[str]:
    """Which of `extras` switch `req` on.

    Empty both for an ordinary requirement and for one this environment
    excludes outright, which is why callers must test the marker first.
    """
    if req.marker is None or req.marker.evaluate({"extra": ""}):
        return []
    return [extra for extra in extras if req.marker.evaluate({"extra": extra})]


@functools.cache
def _gated_requirements(name: str) -> tuple[tuple[Requirement, tuple[str, ...] | None], ...]:
    """Each requirement of `name`, with the extras that switch it on or None if always on.

    Evaluated once per distribution: marker evaluation is what the walk spends
    its time on once metadata is indexed.
    """
    extras = _extras(name)
    return tuple(
        (
            req,
            None
            if req.marker is None or req.marker.evaluate({"extra": ""})
            else tuple(_gating_extras(req, extras)),
        )
        for req in _requirements(name)
    )


def _wanted(parent: str, gating: tuple[str, ...] | None) -> bool:
    """Whether a requirement is part of this environment, and so part of the closure."""
    if gating is None:
        return True
    # No extra switches it on either, so the marker excluded it for some other
    # reason — a platform or a Python version this environment is not.
    return any(_extra_is_installed(parent, extra) for extra in gating)


@functools.cache
def _extra_is_installed(name: str, extra: str) -> bool:
    """Whether every requirement this extra switches on is present.

    The rule for extras, which no installed-package metadata records: an extra
    counts as in use when all of its own requirements are installed. That picks
    up `ecoscope[platform]` in a platform environment and leaves `[gcp]` out of
    a local one, without asking the workflow which extras it asked for.
    """
    members = [req for req, gating in _gated_requirements(name) if gating and extra in gating]
    return all(_installed_version(req.name) is not None for req in members)


@functools.cache
def _closure_fingerprint(roots: tuple[str, ...]) -> str:
    """Digest the installed distributions transitively reachable from `roots`.

    A task's own version only moves on its own release, so without this a new
    pandas or geopandas under an unchanged `ecoscope` would serve results the
    new code would not produce. Only installed requirements are followed: a
    missing optional dependency is not part of this environment.

    Which extras of a root are in use is unrecorded, so `_wanted` infers them.
    Below the roots, an extra is followed only when a requirement that reached
    the distribution names it. Inferring there too pulls in `pandas[xml]` or a
    `[test]` extra whenever an unrelated package happens to install lxml or
    pytest, giving every workflow with extra tooling a private cache.
    """
    found: dict[str, str] = {}
    followed: dict[str, set[str]] = {}
    queue: deque[tuple[str, frozenset[str] | None]] = deque((root, None) for root in roots)
    while queue:
        raw, requested = queue.popleft()
        name = canonicalize_name(raw)
        version = _installed_version(name)
        if version is None:
            continue
        first = name not in found
        found[name] = version
        if requested is None:
            if not first:
                continue
            wanted = [req for req, gating in _gated_requirements(name) if _wanted(name, gating)]
        else:
            new = requested - followed.setdefault(name, set())
            if not first and not new:
                continue
            followed[name] |= new
            wanted = [
                req
                for req, gating in _gated_requirements(name)
                if (gating is None and first)
                or (gating and new & {canonicalize_name(e) for e in gating})
            ]
        queue.extend(
            (req.name, frozenset(canonicalize_name(e) for e in req.extras)) for req in wanted
        )

    lines = "\n".join(f"{name}=={version}" for name, version in sorted(found.items()))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()[:12]


@functools.cache
def distribution_version(anchor: str) -> str | None:
    """Return a version string for the distribution providing `anchor`, else None.

    None means "do not cache this step". Failing closed is the point: without a
    version, a code change would not move the key and the cache would serve the
    old result indefinitely. A module can map to more than one distribution, so
    all of them are folded in, sorted for stability, followed by a digest of
    their whole installed dependency closure.

    The closure rather than the workflow's lock hash: every workflow resolves
    its own environment, so a lock hash would give each one a private cache.
    """
    top_level = anchor.split(".")[0]
    dists = _packages_distributions().get(top_level)
    if not dists:
        return None
    roots = tuple(sorted(set(dists)))
    try:
        versions = [_installed_version(d) for d in roots]
        if None in versions:
            return None
        own = ";".join(f"{d}=={v}" for d, v in zip(roots, versions, strict=True))
        return f"{own}+deps:{_closure_fingerprint(roots)}"
    except Exception as e:  # noqa: BLE001  # unreadable metadata must not serve stale results
        warnings.warn(
            f"Could not fingerprint the dependencies of {', '.join(roots)} ({e!r}); "
            f"steps from {top_level!r} will not be cached.",
            stacklevel=2,
        )
        return None


def task_identity(spec: CacheSpec, resolved: ResolvedTask) -> str | None:
    """Identify the code a step runs, or None if it cannot be pinned.

    The `epoch` setting is the manual invalidator, for when a distribution version
    cannot move: development against editable installs, or an unreleased task
    stack. Derive it from the *task library* build — the image layer or lock
    hash the tasks come from — not from the per-workflow image, or two
    workflows shipping the same library would never share an entry.
    """
    version = distribution_version(resolved.anchor)
    if version is None:
        return None
    epoch = active_settings().epoch
    return f"{resolved.anchor}.{resolved.function}@{version}#{spec.signature}#{epoch}"


def step_identity_with_reason(
    spec: CacheSpec, resolved: ResolvedTask, task_instance_id: str, method: str = "call"
) -> tuple[str | None, str | None]:
    """Compute this step's cache key, or None and the reason it has none."""
    task = task_identity(spec, resolved)
    if task is None:
        return None, f"no distribution version for {resolved.anchor!r}"

    upstream_inputs: dict[str, list[str]] = {}
    for argname, dep_ids in spec.upstream_inputs.items():
        digests = []
        for dep_id in dep_ids:
            identity = _upstream(dep_id)
            if identity is None:
                return None, f"upstream {dep_id!r} uncacheable"
            digests.append(identity)
        upstream_inputs[argname] = digests

    key = {
        "task": task,
        "structure": resolved.structures.get(method),
        "fixed_inputs": spec.fixed_inputs,
        "env": {name: os.environ.get(name, "") for name in spec.env},
        "params": step_params(task_instance_id),
        "upstream_inputs": upstream_inputs,
    }
    if spec.scoped:
        # Only steps that read the world. Credentials reach tasks as env vars
        # keyed by connection name, so byte-identical params can address
        # different tenants; a derived step cannot be reached without already
        # holding the same input digests, so scoping it would only mean that a
        # fresh token costs a whole cold run instead of one source refetch.
        key["scope"] = active_settings().scope

    return json_digest(key), None


def step_identity(
    spec: CacheSpec, resolved: ResolvedTask, task_instance_id: str, method: str = "call"
) -> str | None:
    """Compute this step's cache key, or None if it cannot be cached.

    Returns None when the code cannot be pinned, or when any upstream step was
    itself uncacheable — uncacheability propagates down the DAG, because a key
    that omits an unknown input would collide across genuinely different runs.
    """
    return step_identity_with_reason(spec, resolved, task_instance_id, method)[0]
