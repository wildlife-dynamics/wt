"""Tests for step caching: the builder, the key, and hit/miss behaviour."""

import dataclasses
import inspect
import re
import sys
import warnings
from pathlib import Path
from typing import Annotated, Any

import pytest
from pydantic import BaseModel, Field
from wt_contracts import CodecDeclarationError, CodecRef, ModelDumpCacheable, declared_structure

from wt_task import task
from wt_task.cache import (
    JSON,
    CacheCorruptionError,
    CacheEntry,
    CacheMismatchWarning,
    CacheSpec,
    Codec,
    _key,
    _runtime,
    record,
    resolve_task,
    run_report,
    run_scope,
)
from wt_task.cache._key import (
    _packages_distributions,
    distribution_fingerprint,
    step_identity,
    step_params,
)
from wt_task.executors.python import PythonExecutor
from wt_task.skip import SKIP_SENTINEL

# The anchor now comes from the task function's own module, and a function
# defined in a test module belongs to no distribution — which the cache treats
# as "cannot pin this code, do not cache it".
ANCHOR = "test_cache"

Json = Annotated[Any, CodecRef("wt_task.cache:JSON")]
"""A return type that declares the JSON codec, for tasks returning loose data."""


@pytest.fixture(autouse=True)
def tasks_belong_to_a_distribution(monkeypatch):
    real = _packages_distributions()
    monkeypatch.setattr(_key, "_packages_distributions", lambda: {**real, ANCHOR: ["wt-task"]})
    distribution_fingerprint.cache_clear()
    yield
    distribution_fingerprint.cache_clear()


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_CACHE__STORE", str(tmp_path / "cache"))
    monkeypatch.delenv("WT_CACHE__EPOCH", raising=False)
    monkeypatch.delenv("WT_CACHE__SCOPE", raising=False)
    monkeypatch.setenv("WT_CACHE__STRICT", "1")
    return tmp_path / "cache"


SKIP_REF = {"k": "ref", "ref": "wt_task.cache:SKIP", "type": None}

_IS_HEX = re.compile(r"[0-9a-f]{64}")
_IN_TREE_DIR = re.compile(r"tree/v2/[0-9a-f]{64}")


def frame_like(codec_id):
    """A leaf codec standing in for a library's frame codec, under any id."""
    return Codec(
        codec_id=codec_id,
        media_type="application/json",
        types=(dict,),
        encode=JSON.encode,
        decode=JSON.decode,
        digest=JSON.digest,
    )


FRAME = frame_like("test.frame/v1")
UNSAFE = frame_like("../escape/v1")
Frame = Annotated[dict[str, Any], CodecRef("test_cache:FRAME")]
Unsafe = Annotated[dict[str, Any], CodecRef("test_cache:UNSAFE")]


def spec(**kwargs):
    kwargs.setdefault("signature", "signature-1")
    return CacheSpec(**kwargs)


def outcome(ids, task_instance_id):
    return ids[task_instance_id].outcome


def counting_task():
    calls = []

    @task
    def add(a: int, b: int) -> int:
        calls.append((a, b))
        return a + b

    return add, calls


# --- the builder -----------------------------------------------------------


def test_cached_returns_a_new_task_and_leaves_the_original_alone():
    add, _ = counting_task()
    cached = add.set_task_instance_id("step").cached(spec())
    assert cached is not add
    assert add.cache_spec is None
    assert cached.cache_spec.signature == "signature-1"
    # The other half of the identity comes from the function, not the spec.
    assert cached.encoding.function == "add"


def test_cached_chains_with_the_other_builders():
    add, _ = counting_task()
    chained = (
        add.validate()
        .set_task_instance_id("step")
        .handle_errors()
        .set_task_instance_id("step")
        .cached(spec())
    )
    assert chained.cache_spec is not None
    assert chained.task_instance_id == "step"
    assert chained.call("1", "2") == 3


@pytest.mark.parametrize("executor", ["python", PythonExecutor()])
def test_set_executor_preserves_the_cache_spec(executor):
    # `set_executor` rebuilds the task from named fields, so a new field is easy
    # to drop silently; that would turn caching off wherever an executor is set.
    add, _ = counting_task()
    moved = add.set_task_instance_id("step").cached(spec()).set_executor(executor)
    assert moved.cache_spec.signature == "signature-1"
    assert moved.encoding.function == "add"
    assert moved.task_instance_id == "step"


# --- inert by default ------------------------------------------------------


def test_cache_is_inert_when_the_store_is_unset(monkeypatch):
    monkeypatch.delenv("WT_CACHE__STORE", raising=False)
    add, calls = counting_task()
    cached = add.set_task_instance_id("step").cached(spec())
    assert [cached.call(1, 2), cached.call(1, 2)] == [3, 3]
    assert len(calls) == 2  # ran both times


# --- hit and miss ----------------------------------------------------------


def test_second_call_hits_and_does_not_execute(cache_dir):
    add, calls = counting_task()
    cached = add.set_task_instance_id("step").cached(spec())
    assert cached.call(1, 2) == 3
    assert cached.call(1, 2) == 3
    assert len(calls) == 1


def test_hit_returns_the_same_value_a_miss_would(cache_dir):
    add, _ = counting_task()
    cached = add.set_task_instance_id("step").cached(spec())
    assert cached.call(1, 2) == cached.call(1, 2)


def test_changed_params_miss(cache_dir):
    # Params reach the key through `run_scope`, not through the step's spec:
    # the DAG hands the whole run's parameters over once.
    add, calls = counting_task()
    cached = add.set_task_instance_id("step").cached(spec())
    for n in (1, 2):
        with run_scope(params={"step": {"n": n}}):
            cached.call(1, 2)
    assert len(calls) == 2


def test_another_steps_params_do_not_move_this_steps_key(cache_dir):
    add, calls = counting_task()
    cached = add.set_task_instance_id("step").cached(spec())
    for n in (1, 2):
        with run_scope(params={"step": {"n": 7}, "elsewhere": {"n": n}}):
            cached.call(1, 2)
    assert len(calls) == 1


def test_params_default_to_empty_outside_a_scope(cache_dir):
    add, calls = counting_task()
    cached = add.set_task_instance_id("step").cached(spec())
    cached.call(1, 2)
    with run_scope(params={}):
        cached.call(1, 2)
    assert len(calls) == 1


def test_changed_static_args_miss(cache_dir):
    add, calls = counting_task()
    add.set_task_instance_id("step").cached(spec(fixed_inputs="hash-a")).call(1, 2)
    add.set_task_instance_id("step").cached(spec(fixed_inputs="hash-b")).call(1, 2)
    assert len(calls) == 2


def test_changed_env_arg_misses(cache_dir, monkeypatch):
    # The spec names the variable; the runtime reads its value when it builds
    # the key, so a per-run results directory moves it.
    add, calls = counting_task()
    cached = add.set_task_instance_id("step").cached(spec(env=["WT_RESULTS"]))
    for root in ("/run/1", "/run/2"):
        monkeypatch.setenv("WT_RESULTS", root)
        cached.call(1, 2)
    assert len(calls) == 2


def test_an_unchanged_env_value_still_hits(cache_dir, monkeypatch):
    add, calls = counting_task()
    monkeypatch.setenv("WT_RESULTS", "/run/1")
    cached = add.set_task_instance_id("step").cached(spec(env=["WT_RESULTS"]))
    cached.call(1, 2)
    cached.call(1, 2)
    assert len(calls) == 1


def test_changed_recipe_misses(cache_dir):
    add, calls = counting_task()
    add.set_task_instance_id("step").cached(spec(signature="v1")).call(1, 2)
    add.set_task_instance_id("step").cached(spec(signature="v2")).call(1, 2)
    assert len(calls) == 2


def test_epoch_invalidates_everything(cache_dir, monkeypatch):
    add, calls = counting_task()
    add.set_task_instance_id("step").cached(spec()).call(1, 2)
    monkeypatch.setenv("WT_CACHE__EPOCH", "image-sha-2")
    add.set_task_instance_id("step").cached(spec()).call(1, 2)
    assert len(calls) == 2


def test_scope_separates_tenants_for_a_step_that_reads_the_world(cache_dir, monkeypatch):
    # Credentials arrive as env vars keyed by connection name, so without a
    # scope two tenants sharing a connection name would share cache entries.
    add, calls = counting_task()
    monkeypatch.setenv("WT_CACHE__SCOPE", "tenant-a")
    add.set_task_instance_id("step").cached(spec(scoped=True)).call(1, 2)
    monkeypatch.setenv("WT_CACHE__SCOPE", "tenant-b")
    add.set_task_instance_id("step").cached(spec(scoped=True)).call(1, 2)
    assert len(calls) == 2


def test_scope_is_ignored_by_a_derived_step(cache_dir, monkeypatch):
    # A derived step is a pure function of its input digests, and nobody can
    # reach one without already holding the same content. Scoping it would mean
    # a fresh token costs a cold run rather than one source refetch.
    add, calls = counting_task()
    for scope in ("tenant-a", "tenant-b"):
        monkeypatch.setenv("WT_CACHE__SCOPE", scope)
        add.set_task_instance_id("step").cached(spec()).call(1, 2)
    assert len(calls) == 1


def test_a_new_scope_misses_the_source_and_still_hits_everything_below(cache_dir, monkeypatch):
    source_calls = []
    derived_calls = []

    @task
    def read_world() -> int:
        source_calls.append(1)
        return 42  # the same content, fetched under a new token

    @task
    def transform(n: int) -> int:
        derived_calls.append(n)
        return n * 2

    source = read_world.set_task_instance_id("source").cached(spec(scoped=True))
    derived = transform.set_task_instance_id("derived").cached(
        spec(upstream_inputs={"n": ["source"]})
    )
    for scope in ("token-1", "token-2"):
        monkeypatch.setenv("WT_CACHE__SCOPE", scope)
        with run_scope() as ids:
            source.call()
            derived.call(42)
            outcomes = (outcome(ids, "source"), outcome(ids, "derived"))

    assert source_calls == [1, 1]  # refetched under the new principal
    assert derived_calls == [42]  # but the step below it hit
    assert outcomes == ("miss", "hit")


def test_an_io_step_with_no_scope_is_never_served_or_stored(cache_dir):
    # Unscoped, every tenant sharing a connection name would share the key.
    add, calls = counting_task()
    cached = add.set_task_instance_id("step").cached(spec(scoped=True))
    with run_scope() as ids:
        cached.call(1, 2)
        cached.call(1, 2)
        row = ids["step"]
    assert len(calls) == 2
    assert (row.outcome, row.reason) == ("unservable", "io step with WT_CACHE__SCOPE unset")
    assert not (cache_dir / "keys").exists()


def test_an_unscoped_io_step_still_lets_everything_below_hit(cache_dir):
    @task
    def read_world() -> int:
        return 42

    derived_calls = []

    @task
    def transform(n: int) -> int:
        derived_calls.append(n)
        return n * 2

    source = read_world.set_task_instance_id("source").cached(spec(scoped=True))
    derived = transform.set_task_instance_id("derived").cached(
        spec(upstream_inputs={"n": ["source"]})
    )
    for _ in range(2):
        with run_scope():
            source.call()
            derived.call(42)
    assert derived_calls == [42]


# --- what cannot be cached -------------------------------------------------


def test_unresolvable_distribution_is_not_cached(cache_dir, monkeypatch):
    # The anchor is the task function's own module; a task from a package that
    # is not installed cannot be pinned to a version, so it is not cached.
    add, calls = counting_task()
    monkeypatch.setattr(add.func, "__module__", "no_such_distribution_xyz")
    cached = add.set_task_instance_id("step").cached(spec())
    cached.call(1, 2)
    cached.call(1, 2)
    assert len(calls) == 2


def test_distribution_version_fails_closed():
    assert distribution_fingerprint("no_such_distribution_xyz") is None
    assert distribution_fingerprint("wt_task") is not None


def test_a_return_type_with_no_declared_codec_is_not_cached(cache_dir):
    calls = []

    @task
    def make_object() -> object:
        calls.append(1)
        return object()

    cached = make_object.set_task_instance_id("step").cached(spec())
    cached.call()
    cached.call()
    assert len(calls) == 2


def test_uncacheable_step_marks_itself_so_for_dependents(cache_dir):
    @task
    def make_object() -> object:
        return object()

    with run_scope() as ids:
        make_object.set_task_instance_id("producer").cached(spec()).call()
        assert ids["producer"].digest is None
        assert outcome(ids, "producer") == "uncacheable"


def test_uncacheability_propagates_downstream(cache_dir):
    add, calls = counting_task()
    with run_scope():
        record("producer", None, "uncacheable")
        consumer = add.set_task_instance_id("consumer").cached(
            spec(upstream_inputs={"a": ["producer"]})
        )
        consumer.call(1, 2)
        consumer.call(1, 2)
    assert len(calls) == 2


def test_unknown_dependency_is_treated_as_uncacheable(cache_dir):
    add, calls = counting_task()
    with run_scope():
        consumer = add.set_task_instance_id("consumer").cached(
            spec(upstream_inputs={"a": ["never-ran"]})
        )
        consumer.call(1, 2)
        consumer.call(1, 2)
    assert len(calls) == 2


# --- derivation through the DAG --------------------------------------------


def test_downstream_hits_when_upstream_identity_is_unchanged(cache_dir):
    add, calls = counting_task()
    consumer = add.set_task_instance_id("consumer").cached(
        spec(upstream_inputs={"a": ["producer"]})
    )
    for _ in range(2):
        with run_scope():
            record("producer", "same", "miss")
            consumer.call(1, 2)
    assert len(calls) == 1


def test_downstream_misses_when_upstream_identity_moves(cache_dir):
    add, calls = counting_task()
    consumer = add.set_task_instance_id("consumer").cached(
        spec(upstream_inputs={"a": ["producer"]})
    )
    for upstream in ("first", "second"):
        with run_scope():
            record("producer", upstream, "miss")
            consumer.call(1, 2)
    assert len(calls) == 2


def test_every_step_contributes_its_output_digest(cache_dir):
    # Not its own identity: the key below a step must answer "will this produce
    # the same output?", and only the digest does.
    add, _ = counting_task()
    with run_scope() as ids:
        s = spec()
        cached = add.set_task_instance_id("producer").cached(s)
        cached.call(1, 2)
        key, _ = step_identity(s, cached.encoding, step_params("producer"))
        assert ids["producer"].digest != key
        assert _IN_TREE_DIR.fullmatch(ids["producer"].digest)


def test_a_step_rerunning_with_unchanged_output_cuts_off_recomputation(cache_dir):
    producer_calls = []
    consumer_calls = []

    @task
    def produce(run: int) -> int:
        producer_calls.append(run)
        return 42  # same data every run, despite a changing argument

    @task
    def transform(n: int) -> int:
        consumer_calls.append(n)
        return n * 2

    consumer = transform.set_task_instance_id("consumer").cached(
        spec(upstream_inputs={"n": ["producer"]})
    )
    for run in (1, 2):
        # A changing param forces the producer itself to re-execute.
        with run_scope(params={"producer": {"run": run}}):
            produce.set_task_instance_id("producer").cached(spec()).call(run)
            consumer.call(42)

    assert producer_calls == [1, 2]  # producer re-ran both runs
    assert consumer_calls == [42]  # but the step below it still hit


def test_a_step_returning_changed_data_invalidates_downstream(cache_dir):
    consumer_calls = []

    @task
    def produce(run: int) -> int:
        return run  # different data each run

    @task
    def transform(n: int) -> int:
        consumer_calls.append(n)
        return n * 2

    consumer = transform.set_task_instance_id("consumer").cached(
        spec(upstream_inputs={"n": ["producer"]})
    )
    for run in (1, 2):
        with run_scope(params={"producer": {"run": run}}):
            produce.set_task_instance_id("producer").cached(spec()).call(run)
            consumer.call(run)

    assert consumer_calls == [1, 2]


def test_two_steps_computing_the_same_value_share_a_downstream_key(cache_dir):
    # Content promotion makes keys below a step depend on what it produced, not
    # on which recipe produced it.
    @task
    def seven() -> int:
        return 7

    @task
    def also_seven() -> int:
        return 3 + 4

    add, calls = counting_task()
    consumer = add.set_task_instance_id("consumer").cached(
        spec(upstream_inputs={"n": ["producer"]})
    )
    for producer in (seven, also_seven):
        with run_scope():
            producer.set_task_instance_id("producer").cached(spec()).call()
            consumer.call(1, 2)
    assert len(calls) == 1


# --- opting out of being served -------------------------------------------


def test_an_unservable_step_always_executes(cache_dir):
    add, calls = counting_task()
    cached = add.set_task_instance_id("step").cached(spec(servable=False))
    assert [cached.call(1, 2), cached.call(1, 2)] == [3, 3]
    assert len(calls) == 2


def test_an_unservable_step_stores_nothing(cache_dir):
    # Verify mode relies on this: a step already declared untrustworthy has no
    # baseline to compare against, so there is nothing to learn from it.
    add, _ = counting_task()
    add.set_task_instance_id("step").cached(spec(servable=False)).call(1, 2)
    assert [p for p in cache_dir.rglob("*") if p.is_file()] == []


def test_an_unservable_step_does_not_poison_its_dependents(cache_dir):
    producer_calls = []
    consumer_calls = []

    @task
    def produce() -> int:
        producer_calls.append(1)
        return 42

    @task
    def transform(n: int) -> int:
        consumer_calls.append(n)
        return n * 2

    consumer = transform.set_task_instance_id("consumer").cached(
        spec(upstream_inputs={"n": ["producer"]})
    )
    for _ in range(2):
        with run_scope():
            produce.set_task_instance_id("producer").cached(spec(servable=False)).call()
            consumer.call(42)

    assert producer_calls == [1, 1]  # never served
    assert consumer_calls == [42]  # but everything below it still hit


def test_an_unservable_step_promotes_its_output_digest(cache_dir):
    add, _ = counting_task()
    with run_scope() as ids:
        add.set_task_instance_id("producer").cached(spec(servable=False)).call(1, 2)
        assert _IN_TREE_DIR.fullmatch(ids["producer"].digest)


# --- verify mode -----------------------------------------------------------


@pytest.fixture
def verifying(monkeypatch):
    monkeypatch.setenv("WT_CACHE__VERIFY", "1")


def test_verify_mode_reports_a_nondeterministic_step_by_name(cache_dir, monkeypatch):
    results = iter([1, 2])

    @task
    def unstable() -> int:
        return next(results)

    cached = unstable.set_task_instance_id("wobbly").cached(spec())
    cached.call()  # the baseline run

    monkeypatch.setenv("WT_CACHE__VERIFY", "1")
    with pytest.warns(CacheMismatchWarning, match="'wobbly'"):
        assert cached.call() == 2  # the fresh value, not the stored one


def test_verify_mode_is_quiet_for_a_deterministic_step(cache_dir, monkeypatch):
    add, calls = counting_task()
    cached = add.set_task_instance_id("step").cached(spec())
    cached.call(1, 2)

    monkeypatch.setenv("WT_CACHE__VERIFY", "1")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert cached.call(1, 2) == 3
    assert [w for w in caught if issubclass(w.category, CacheMismatchWarning)] == []
    assert len(calls) == 2  # executed anyway, which is the point of verify mode


def test_verify_mode_does_not_overwrite_the_baseline(cache_dir, monkeypatch):
    # The baseline has to stay fixed, or a second verify run would compare a
    # nondeterministic step against its own last output and report nothing.
    results = iter([1, 2, 3])

    @task
    def unstable() -> int:
        return next(results)

    cached = unstable.set_task_instance_id("wobbly").cached(spec())
    cached.call()
    stored = {p: p.read_bytes() for p in cache_dir.rglob("*") if p.is_file()}

    monkeypatch.setenv("WT_CACHE__VERIFY", "1")
    for _ in range(2):
        with pytest.warns(CacheMismatchWarning):
            cached.call()
    assert {p: p.read_bytes() for p in cache_dir.rglob("*") if p.is_file()} == stored


def test_verify_mode_skips_a_step_that_was_never_stored(cache_dir, verifying):
    add, _ = counting_task()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        add.set_task_instance_id("step").cached(spec()).call(1, 2)
    assert [w for w in caught if issubclass(w.category, CacheMismatchWarning)] == []


def test_verify_mode_is_inert_without_a_store(monkeypatch):
    monkeypatch.delenv("WT_CACHE__STORE", raising=False)
    monkeypatch.setenv("WT_CACHE__VERIFY", "1")
    add, calls = counting_task()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert add.set_task_instance_id("step").cached(spec()).call(1, 2) == 3
    assert caught == []
    assert len(calls) == 1


# --- values that must survive the round trip -------------------------------


def test_skip_sentinel_round_trips_through_the_store(cache_dir):
    calls = []

    @task
    def maybe(x: int) -> int:
        calls.append(x)
        return x

    cached = maybe.skipif([lambda *a: True]).set_task_instance_id("step").cached(spec())
    assert cached.call(1) is SKIP_SENTINEL
    # A hit must hand back the sentinel, not resurrect the skipped step.
    assert cached.call(1) is SKIP_SENTINEL
    assert calls == []


@pytest.mark.parametrize(
    "value",
    [0, 1, -1, 1.5, "", "text", True, False, None, [], [1, "a"], {}, {"a": [1, {"b": 2}]}],
)
def test_json_values_round_trip(cache_dir, value):
    @task
    def produce() -> Json:
        return value

    cached = produce.set_task_instance_id("step").cached(spec())
    assert cached.call() == value
    assert cached.call() == value


def test_bytes_round_trip(cache_dir):
    @task
    def produce() -> bytes:
        return b"\x00\x01binary"

    cached = produce.set_task_instance_id("step").cached(spec())
    assert cached.call() == b"\x00\x01binary"
    assert cached.call() == b"\x00\x01binary"


# --- map and mapvalues cache as one step -----------------------------------


def test_map_caches_the_whole_step(cache_dir):
    calls = []

    @task
    def square(x: int) -> int:
        calls.append(x)
        return x * x

    cached = square.set_task_instance_id("step").cached(spec())
    assert cached.map("x", [1, 2, 3]) == [1, 4, 9]
    assert cached.map("x", [1, 2, 3]) == [1, 4, 9]
    assert calls == [1, 2, 3]  # one entry for the step, not one per item


def test_mapvalues_caches_the_whole_step(cache_dir):
    calls = []

    @task
    def double(x: int) -> int:
        calls.append(x)
        return x * 2

    cached = double.set_task_instance_id("step").cached(spec())
    first = cached.mapvalues("x", [("a", 1), ("b", 2)])
    second = cached.mapvalues("x", [("a", 1), ("b", 2)])
    assert first == [("a", 2), ("b", 4)]
    assert second == first
    assert calls == [1, 2]


def test_a_hit_gives_back_mapvalues_keys_a_downstream_step_can_group_by(cache_dir):
    # The shape the real events spec produces: a `CompositeFilter` key, which
    # is a tuple of 3-tuples. A hit that handed back lists would blow up in the
    # next `groupbykey` with `TypeError: unhashable type: 'list'`, so the keys
    # have to come back hashable and equal to what the miss produced.
    calls = []

    @task
    def rename(df: str) -> str:
        calls.append(df)
        return df.upper()

    keys = [
        (("event_type", "=", "fire"),),
        (("event_type", "=", "flood"), ("month", "=", "may")),
    ]
    argvalues = [(k, name) for k, name in zip(keys, ["a", "b"], strict=True)]

    cached = rename.set_task_instance_id("step").cached(spec())
    miss = cached.mapvalues("df", argvalues)
    hit = cached.mapvalues("df", argvalues)

    assert calls == ["a", "b"]  # the second call really was served
    assert hit == miss
    assert {k for k, _ in hit} == set(keys)  # hashable, and the same keys
    assert dict(hit) == {keys[0]: "A", keys[1]: "B"}


# --- failure handling ------------------------------------------------------


def test_a_corrupt_payload_fails_loudly_under_strict(cache_dir):
    add, _ = counting_task()
    cached = add.set_task_instance_id("step").cached(spec())
    cached.call(1, 2)

    payload = next(p for p in (cache_dir / "content").rglob("*") if p.is_file())
    payload.write_bytes(b"not json at all")

    # Never a silent wrong value: the entry names an installed codec and a
    # payload that is present, so the store is lying.
    with pytest.raises(CacheCorruptionError):
        cached.call(1, 2)


def test_a_corrupt_payload_warns_recomputes_and_repairs_without_strict(cache_dir, monkeypatch):
    monkeypatch.delenv("WT_CACHE__STRICT")
    add, calls = counting_task()
    cached = add.set_task_instance_id("step").cached(spec())
    cached.call(1, 2)

    payload = next(p for p in (cache_dir / "content").rglob("*") if p.is_file())
    payload.write_bytes(b"not json at all")

    with pytest.warns(UserWarning, match="Could not decode"):
        assert cached.call(1, 2) == 3
    assert cached.call(1, 2) == 3  # the recompute rewrote the payload
    assert len(calls) == 2


def test_a_raising_task_stores_nothing(cache_dir):
    calls = []

    @task
    def boom() -> int:
        calls.append(1)
        raise ValueError("nope")

    cached = boom.set_task_instance_id("step").cached(spec())
    for _ in range(2):
        with pytest.raises(ValueError):
            cached.call()
    assert len(calls) == 2


def test_an_unwritable_store_degrades_to_running(tmp_path, monkeypatch):
    unwritable = tmp_path / "ro"
    unwritable.mkdir()
    monkeypatch.setenv("WT_CACHE__STORE", str(unwritable))
    unwritable.chmod(0o500)
    try:
        add, calls = counting_task()
        cached = add.set_task_instance_id("step").cached(spec())
        with pytest.warns(UserWarning, match="Could not write cache entry"):
            assert cached.call(1, 2) == 3
        assert len(calls) == 1
    finally:
        unwritable.chmod(0o700)


def test_a_refused_write_still_lets_everything_below_hit(cache_dir, monkeypatch):
    # The `combined_df` case: a frame the codec can digest but not encode.
    real_save = _runtime._save

    def refuse_the_source(store, identity, tree, content_id, value):
        return value != 42 and real_save(store, identity, tree, content_id, value)

    monkeypatch.setattr(_runtime, "_save", refuse_the_source)

    @task
    def read_world() -> int:
        return 42

    derived_calls = []

    @task
    def transform(n: int) -> int:
        derived_calls.append(n)
        return n * 2

    source = read_world.set_task_instance_id("source").cached(spec())
    derived = transform.set_task_instance_id("derived").cached(
        spec(upstream_inputs={"n": ["source"]})
    )
    for _ in range(2):
        with run_scope() as ids:
            source.call()
            derived.call(42)
    assert derived_calls == [42]
    assert ids["source"].outcome == "unservable"
    assert ids["source"].reason == "store would not accept the write"


def test_argument_collecting_several_upstreams_folds_in_all_of_them(cache_dir):
    # `widgets: [${{ workflow.a.return }}, ${{ workflow.b.return }}]` binds one
    # argument to several steps; moving any of them must move the key.
    add, calls = counting_task()
    consumer = add.set_task_instance_id("consumer").cached(
        spec(upstream_inputs={"widgets": ["a", "b"]})
    )
    for b_identity in ("b1", "b1", "b2"):
        with run_scope():
            record("a", "a1", "miss")
            record("b", b_identity, "miss")
            consumer.call(1, 2)
    assert len(calls) == 2  # hit on the repeat, miss once `b` moved


def test_one_uncacheable_upstream_among_several_blocks_the_step(cache_dir):
    add, calls = counting_task()
    consumer = add.set_task_instance_id("consumer").cached(
        spec(upstream_inputs={"widgets": ["a", "b"]})
    )
    for _ in range(2):
        with run_scope():
            record("a", "a1", "miss")
            record("b", None, "uncacheable")
            consumer.call(1, 2)
    assert len(calls) == 2


# --- the structure the step actually returns -------------------------------


def test_a_mapped_step_wraps_the_declared_structure_in_a_list(cache_dir):
    @task
    def to_path(name: str) -> Path:
        return Path("/var/data") / name

    cached = to_path.set_task_instance_id("step").cached(spec())
    first = cached.map("name", ["a", "b"])
    assert cached.map("name", ["a", "b"]) == first == [Path("/var/data/a"), Path("/var/data/b")]


def test_a_per_element_skip_survives_a_mapped_round_trip(cache_dir):
    # `skipif` can turn any element into the sentinel whatever the annotation
    # says, so the wrapped structure has to admit it at every position.
    calls = []

    @task
    def double(x: int) -> int:
        calls.append(x)
        return x * 2

    cached = double.skipif([lambda *a: a[0] < 0]).set_task_instance_id("step").cached(spec())
    first = cached.map("x", [1, -1, 3])
    second = cached.map("x", [1, -1, 3])
    assert [v for v in first if not isinstance(v, type(SKIP_SENTINEL))] == [2, 6]
    assert isinstance(second[1], type(SKIP_SENTINEL))
    assert calls == [1, 3]  # one entry for the step, served the second time


def test_a_return_type_that_changes_shape_misses_under_an_unchanged_version(cache_dir, monkeypatch):
    # An editable install moves no version, and the signature hash covers only
    # the parameters, so the key itself has to move with the declared structure
    # — or the old entry decodes into the new dataclass and fails the run.
    module = sys.modules[__name__]

    def build(*names):
        point = dataclasses.make_dataclass("Point", [(n, int) for n in names])
        point.__module__ = __name__
        monkeypatch.setattr(module, "Point", point, raising=False)

        def make() -> point:  # type: ignore[valid-type]
            return point(*range(len(names)))

        return task(make).set_task_instance_id("step").cached(spec()), point

    old, _ = build("x")
    old.call()
    new, point = build("x", "y")
    assert new.call() == point(0, 1)


def test_a_declared_structure_the_value_does_not_fit_refuses(cache_dir):
    @task
    def produce() -> bytes:
        return object()  # type: ignore[return-value]  # what the declaration forbids

    cached = produce.set_task_instance_id("producer").cached(spec())
    with run_scope() as ids:
        with pytest.warns(UserWarning, match="Not caching"):  # the scope has to outlive the call
            cached.call()
        recorded = ids["producer"]
    assert recorded.outcome == "refused"
    assert recorded.digest is None


# --- the per-run report ----------------------------------------------------


def test_the_run_report_carries_one_row_per_outcome(cache_dir, monkeypatch):
    add, _ = counting_task()

    @task
    def unknown() -> object:
        return object()

    @task
    def unfitting() -> bytes:
        return object()  # type: ignore[return-value]  # what the declaration forbids

    @task
    def unimportable_task() -> Annotated[int, CodecRef("no_such_module_xyz:THING")]:
        return 1

    monkeypatch.delenv("WT_CACHE__STRICT", raising=False)
    with pytest.warns(UserWarning, match="could not be resolved"):
        unimportable = unimportable_task.set_task_instance_id("unimportable").cached(spec())

    add.set_task_instance_id("warm").cached(spec()).call(1, 2)  # a baseline to hit on

    with run_scope():
        add.set_task_instance_id("warm").cached(spec()).call(1, 2)
        add.set_task_instance_id("cold").cached(spec(fixed_inputs="other")).call(3, 4)
        add.set_task_instance_id("unservable").cached(spec(servable=False)).call(5, 6)
        unknown.set_task_instance_id("unknown").cached(spec()).call()
        with pytest.warns(UserWarning, match="Not caching"):
            unfitting.set_task_instance_id("unfitting").cached(spec()).call()
        unimportable.call()
        report = run_report()

    assert {step: row["outcome"] for step, row in report.items()} == {
        "warm": "hit",
        "cold": "miss",
        "unservable": "unservable",
        "unknown": "uncacheable",
        "unfitting": "refused",
        "unimportable": "refused",
    }
    assert "declared codec refs" in report["unimportable"]["reason"]
    assert report["unknown"]["reason"] == "return type declares no codec"


def test_the_run_report_reports_an_inert_cache(monkeypatch):
    monkeypatch.delenv("WT_CACHE__STORE", raising=False)
    add, _ = counting_task()
    with run_scope():
        add.set_task_instance_id("step").cached(spec()).call(1, 2)
        assert run_report()["step"]["outcome"] == "inert"


def test_the_run_report_names_the_upstream_that_blocked_a_step(cache_dir):
    add, _ = counting_task()
    with run_scope():
        record("producer", None, "uncacheable")
        add.set_task_instance_id("consumer").cached(spec(upstream_inputs={"a": ["producer"]})).call(
            1, 2
        )
        assert run_report()["consumer"]["reason"] == "upstream 'producer' uncacheable"


def test_the_run_report_survives_the_scope_that_produced_it(cache_dir):
    # The generated CLI builds its envelope after the DAG's scope has closed.
    add, _ = counting_task()
    with run_scope():
        add.set_task_instance_id("only").cached(spec()).call(1, 2)
    assert run_report()["only"]["outcome"] == "miss"


# --- keys do not depend on what a spec names its steps ---------------------


def test_a_steps_own_id_stays_out_of_its_key(cache_dir):
    # Two workflows naming the same step differently must still share an entry.
    add, calls = counting_task()
    add.set_task_instance_id("fetch_events").cached(spec()).call(1, 2)
    add.set_task_instance_id("get_events").cached(spec()).call(1, 2)
    assert len(calls) == 1


def test_an_upstreams_id_stays_out_of_its_dependents_key(cache_dir):
    # `inputs` folds in what the upstream *produced*, never what it was called.
    add, calls = counting_task()
    for producer_id in ("fetch", "get_events"):
        with run_scope():
            record(producer_id, "same", "miss")
            add.set_task_instance_id("consumer").cached(
                spec(upstream_inputs={"a": [producer_id]})
            ).call(1, 2)
    assert len(calls) == 1


def test_which_argument_an_upstream_feeds_still_moves_the_key(cache_dir):
    add, calls = counting_task()
    for argname in ("a", "b"):
        with run_scope():
            record("producer", "same", "miss")
            add.set_task_instance_id("consumer").cached(
                spec(upstream_inputs={argname: ["producer"]})
            ).call(1, 2)
    assert len(calls) == 2


# --- the on-disk layout ----------------------------------------------------


def stored(cache_dir, prefix):
    root = cache_dir / prefix
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_keys_are_flat_and_a_structural_step_files_under_the_tree(cache_dir):
    add, _ = counting_task()
    with run_scope() as ids:
        add.set_task_instance_id("producer").cached(spec()).call(1, 2)
        content_id = ids["producer"].digest

    keys = stored(cache_dir, "keys")
    assert len(keys) == 1
    assert _IS_HEX.fullmatch(keys[0])  # no shard directory
    assert stored(cache_dir, "content") == [content_id]
    assert _IN_TREE_DIR.fullmatch(content_id)


def test_a_leaf_rooted_step_files_under_its_codec(cache_dir):
    @task
    def frame() -> Frame:
        return {"rows": [1]}

    with run_scope() as ids:
        frame.set_task_instance_id("step").cached(spec()).call()
        content_id = ids["step"].digest

    assert re.fullmatch(r"test\.frame/v1/[0-9a-f]{64}", content_id)
    assert stored(cache_dir, "content") == [content_id]
    # Filed by codec, but still a tree payload with the tree's digest rule.
    entry = CacheEntry.model_validate_json(
        (cache_dir / "keys" / stored(cache_dir, "keys")[0]).read_bytes()
    )
    assert entry.content_id == content_id
    assert entry.codec_id == "tree/v2"
    assert frame.set_task_instance_id("step").cached(spec()).call() == {"rows": [1]}


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [(Frame, "test.frame/v1"), (Path, "path/v1"), (list[Frame], "tree/v2"), (int, "tree/v2")],
)
def test_the_root_codec_is_the_one_declared_leaf_or_else_the_tree(annotation, expected):
    def f() -> int: ...

    f.__annotations__["return"] = annotation
    encoding = resolve_task(f)
    assert encoding.root_codec == expected
    # The map methods always wrap the value in a list.
    assert encoding.content_dir("map", encoding.tree("map")) == "tree/v2"
    assert encoding.content_dir("call", encoding.tree("call")) == expected


def test_an_unsafe_codec_id_falls_back_to_the_tree(cache_dir):
    @task
    def escape() -> Unsafe:
        return {"rows": [1]}

    with run_scope() as ids:
        escape.set_task_instance_id("step").cached(spec()).call()
        assert _IN_TREE_DIR.fullmatch(ids["step"].digest)
    assert not (cache_dir.parent / "escape").exists()


def test_nothing_is_sharded(cache_dir):
    add, _ = counting_task()
    add.set_task_instance_id("a").cached(spec()).call(1, 2)
    add.set_task_instance_id("b").cached(spec(fixed_inputs="other")).call(3, 4)
    assert all("/" not in key for key in stored(cache_dir, "keys"))
    assert {c.rpartition("/")[0] for c in stored(cache_dir, "content")} == {"tree/v2"}


def test_an_entry_pointing_outside_content_is_a_miss(cache_dir):
    add, calls = counting_task()
    cached = add.set_task_instance_id("step").cached(spec())
    cached.call(1, 2)
    key = next(p for p in (cache_dir / "keys").iterdir() if p.is_file())
    entry = CacheEntry.model_validate_json(key.read_bytes())
    key.write_text(
        entry.model_copy(update={"content_id": "../../keys/" + key.name}).model_dump_json()
    )

    assert cached.call(1, 2) == 3
    assert len(calls) == 2


def test_no_stored_path_contains_a_colon(cache_dir):
    # Object stores and Windows both dislike them, and the `sha256:` and
    # `tree/v2/` namespaces were the only sources.
    add, _ = counting_task()
    add.set_task_instance_id("step").cached(spec()).call(1, 2)
    assert [p for p in cache_dir.rglob("*") if ":" in p.name] == []


def test_the_entry_points_at_its_codec_dir_and_content_digest(cache_dir):
    add, _ = counting_task()
    add.set_task_instance_id("step").cached(spec()).call(1, 2)
    raw = next(p for p in (cache_dir / "keys").rglob("*") if p.is_file())
    entry = CacheEntry.model_validate_json(raw.read_bytes())
    assert _IN_TREE_DIR.fullmatch(entry.content_id)
    assert entry.codec_id == "tree/v2"
    assert entry.media_type == "application/vnd.wt.tree"


# --- what `.cached()` works out from the function --------------------------


def test_the_structure_is_derived_from_the_unwrapped_function():
    # `.validate()`, `.handle_errors()` and `.with_tracing()` all wrap `func`;
    # the declaration lives on the function underneath them.
    @task
    def to_path(name: str) -> Path:
        return Path(name)

    chained = to_path.validate().set_task_instance_id("step").handle_errors().with_tracing()
    assert inspect.unwrap(chained.func) is to_path.func
    assert declared_structure(inspect.unwrap(chained.func)) == declared_structure(to_path.func)
    assert declared_structure(to_path.func) == {
        "k": "ref",
        "ref": "wt_task.cache:PATH",
        "type": None,
    }


def test_a_cached_task_resolves_the_same_anchor_through_the_whole_chain():
    @task
    def to_path(name: str) -> Path:
        return Path(name)

    built = (
        to_path.validate()
        .set_task_instance_id("step")
        .handle_errors()
        .cached(spec())
        .with_tracing()
        .partial(name="/a")
    )
    assert (built.encoding.anchor, built.encoding.function) == (ANCHOR, "to_path")


@pytest.mark.parametrize("method", ["call", "map", "mapvalues"])
def test_every_method_gets_a_tree_wrapping_the_declared_structure(method):
    @task
    def to_path(name: str) -> Path:
        return Path(name)

    encoding = resolve_task(to_path.func)
    assert encoding.tree(method) is not None
    # Whatever the annotation says, a skip can replace the result.
    assert encoding.tree(method).decode(encoding.tree(method).encode(_sample(method)))


def _sample(method):
    if method == "call":
        return Path("/a")
    if method == "map":
        return [Path("/a"), SKIP_SENTINEL]
    return [(("g", "=", "x"), Path("/a"))]


def test_a_task_the_structure_walker_cannot_read_is_uncacheable():
    @task
    def opaque() -> object:
        return object()

    encoding = resolve_task(opaque.func)
    assert encoding.tree("call") is None
    assert encoding.outcome == "uncacheable"
    assert encoding.reason == "return type declares no codec"


def test_an_anchor_that_is_a_private_submodule_is_fine(cache_dir, monkeypatch):
    # The registry's public path and the function's own module can differ; only
    # the top-level package is read, to find the distribution version.
    add, calls = counting_task()
    monkeypatch.setattr(add.func, "__module__", f"{ANCHOR}._private")
    monkeypatch.setattr(_key, "_packages_distributions", lambda: {ANCHOR: ["wt-task"]})
    distribution_fingerprint.cache_clear()
    cached = add.set_task_instance_id("step").cached(spec())
    cached.call(1, 2)
    cached.call(1, 2)
    assert len(calls) == 1


# --- a declaration the type cannot honour ----------------------------------


class _BadCodec(ModelDumpCacheable):
    __wt_codec__ = "wt_task.cache:JSON"


class Unroundtrippable(BaseModel, _BadCodec):
    help_text: str = Field(default="", exclude=True)


def test_a_declaration_error_degrades_to_uncacheable_with_a_warning(monkeypatch):
    monkeypatch.delenv("WT_CACHE__STRICT", raising=False)

    @task
    def make() -> Unroundtrippable:
        return Unroundtrippable()

    with pytest.warns(UserWarning, match="cannot honour"):
        encoding = resolve_task(make.func)
    assert encoding.tree("call") is None
    assert encoding.outcome == "refused"
    assert "help_text" in encoding.reason


def test_a_declaration_error_raises_under_strict_mode(monkeypatch):
    monkeypatch.setenv("WT_CACHE__STRICT", "1")

    @task
    def make() -> Unroundtrippable:
        return Unroundtrippable()

    with pytest.raises(CodecDeclarationError, match="help_text"):
        resolve_task(make.func)


def test_the_key_uses_the_raw_params_the_dag_was_given(cache_dir):
    # `validate` coerces what the function receives; the key is taken from the
    # run's own parameters instead, so it does not depend on that coercion.
    calls = []

    @task
    def add(a: int, b: int) -> int:
        calls.append((a, b))
        return a + b

    cached = add.validate().set_task_instance_id("step").cached(spec())
    with run_scope(params={"step": {"b": "2"}}):
        assert cached.call(a=1, b="2") == 3
    with run_scope(params={"step": {"b": 2}}):
        cached.call(a=1, b="2")

    # The coerced argument is identical either way; the raw param is not.
    assert calls == [(1, 2), (1, 2)]
