"""Tests for step caching: the builder, the key, and hit/miss behaviour."""

import warnings
from pathlib import Path

import pytest

from wt_task import task
from wt_task.cache import (
    CacheCorruptionError,
    CacheMismatchWarning,
    CacheSpec,
    record,
    run_report,
    run_scope,
)
from wt_task.cache._key import distribution_version, step_identity
from wt_task.executors.python import PythonExecutor
from wt_task.skip import SKIP_SENTINEL


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv("WT_CACHE_EPOCH", raising=False)
    monkeypatch.delenv("WT_CACHE_SCOPE", raising=False)
    monkeypatch.setenv("WT_CACHE_STRICT", "1")
    return tmp_path / "cache"


SKIP_REF = {"k": "ref", "ref": "wt_task.cache:SKIP", "type": None}


def spec(task_instance_id="step", **kwargs):
    # `wt_task` is installed in the test environment, so its version resolves and
    # the step is cacheable; an unresolvable anchor is covered separately.
    kwargs.setdefault("anchor", "wt_task")
    kwargs.setdefault("function", "noop")
    kwargs.setdefault("recipe", "recipe-1")
    # The declared structure most of these tasks return: plain JSON-native data.
    kwargs.setdefault("structure", {"k": "dynamic"})
    return CacheSpec(task_instance_id=task_instance_id, **kwargs)


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
    cached = add.cached(spec())
    assert cached is not add
    assert add.cache is None
    assert cached.cache.task_instance_id == "step"


def test_cached_chains_with_the_other_builders():
    add, _ = counting_task()
    chained = add.validate().set_task_instance_id("step").handle_errors().cached(spec())
    assert chained.cache is not None
    assert chained.task_instance_id == "step"
    assert chained.call("1", "2") == 3


def test_set_executor_preserves_the_cache_spec():
    # `set_executor` rebuilds the task from named fields, so a new field is easy
    # to drop silently; that would turn caching off wherever an executor is set.
    add, _ = counting_task()
    assert add.cached(spec()).set_executor("python").cache.task_instance_id == "step"
    assert add.cached(spec()).set_executor(PythonExecutor()).cache.task_instance_id == "step"


# --- inert by default ------------------------------------------------------


def test_cache_is_inert_when_the_store_is_unset(monkeypatch):
    monkeypatch.delenv("WT_CACHE", raising=False)
    add, calls = counting_task()
    cached = add.cached(spec())
    assert [cached.call(1, 2), cached.call(1, 2)] == [3, 3]
    assert len(calls) == 2  # ran both times


# --- hit and miss ----------------------------------------------------------


def test_second_call_hits_and_does_not_execute(cache_dir):
    add, calls = counting_task()
    cached = add.cached(spec())
    assert cached.call(1, 2) == 3
    assert cached.call(1, 2) == 3
    assert len(calls) == 1


def test_hit_returns_the_same_value_a_miss_would(cache_dir):
    add, _ = counting_task()
    cached = add.cached(spec(params={"a": 1}))
    assert cached.call(1, 2) == cached.call(1, 2)


def test_changed_params_miss(cache_dir):
    add, calls = counting_task()
    add.cached(spec(params={"n": 1})).call(1, 2)
    add.cached(spec(params={"n": 2})).call(1, 2)
    assert len(calls) == 2


def test_changed_static_args_miss(cache_dir):
    add, calls = counting_task()
    add.cached(spec(static="hash-a")).call(1, 2)
    add.cached(spec(static="hash-b")).call(1, 2)
    assert len(calls) == 2


def test_changed_env_arg_misses(cache_dir):
    add, calls = counting_task()
    add.cached(spec(env={"root": "/run/1"})).call(1, 2)
    add.cached(spec(env={"root": "/run/2"})).call(1, 2)
    assert len(calls) == 2


def test_changed_recipe_misses(cache_dir):
    add, calls = counting_task()
    add.cached(spec(recipe="v1")).call(1, 2)
    add.cached(spec(recipe="v2")).call(1, 2)
    assert len(calls) == 2


def test_epoch_invalidates_everything(cache_dir, monkeypatch):
    add, calls = counting_task()
    add.cached(spec()).call(1, 2)
    monkeypatch.setenv("WT_CACHE_EPOCH", "image-sha-2")
    add.cached(spec()).call(1, 2)
    assert len(calls) == 2


def test_scope_separates_tenants_for_a_step_that_reads_the_world(cache_dir, monkeypatch):
    # Credentials arrive as env vars keyed by connection name, so without a
    # scope two tenants sharing a connection name would share cache entries.
    add, calls = counting_task()
    monkeypatch.setenv("WT_CACHE_SCOPE", "tenant-a")
    add.cached(spec(scoped=True)).call(1, 2)
    monkeypatch.setenv("WT_CACHE_SCOPE", "tenant-b")
    add.cached(spec(scoped=True)).call(1, 2)
    assert len(calls) == 2


def test_scope_is_ignored_by_a_derived_step(cache_dir, monkeypatch):
    # A derived step is a pure function of its input digests, and nobody can
    # reach one without already holding the same content. Scoping it would mean
    # a fresh token costs a cold run rather than one source refetch.
    add, calls = counting_task()
    for scope in ("tenant-a", "tenant-b"):
        monkeypatch.setenv("WT_CACHE_SCOPE", scope)
        add.cached(spec()).call(1, 2)
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

    source = read_world.cached(spec("source", scoped=True))
    derived = transform.cached(spec("derived", deps={"n": ["source"]}))
    for scope in ("token-1", "token-2"):
        monkeypatch.setenv("WT_CACHE_SCOPE", scope)
        with run_scope() as ids:
            source.call()
            derived.call(42)
            outcomes = (outcome(ids, "source"), outcome(ids, "derived"))

    assert source_calls == [1, 1]  # refetched under the new principal
    assert derived_calls == [42]  # but the step below it hit
    assert outcomes == ("miss", "hit")


# --- what cannot be cached -------------------------------------------------


def test_unresolvable_distribution_is_not_cached(cache_dir):
    add, calls = counting_task()
    cached = add.cached(spec(anchor="no_such_distribution_xyz"))
    cached.call(1, 2)
    cached.call(1, 2)
    assert len(calls) == 2


def test_distribution_version_fails_closed():
    assert distribution_version("no_such_distribution_xyz") is None
    assert distribution_version("wt_task") is not None


def test_a_return_type_with_no_declared_codec_is_not_cached(cache_dir):
    calls = []

    @task
    def make_object() -> object:
        calls.append(1)
        return object()

    cached = make_object.cached(spec(structure=None))
    cached.call()
    cached.call()
    assert len(calls) == 2


def test_uncacheable_step_marks_itself_so_for_dependents(cache_dir):
    @task
    def make_object() -> object:
        return object()

    with run_scope() as ids:
        make_object.cached(spec("producer", structure=None)).call()
        assert ids["producer"].digest is None
        assert outcome(ids, "producer") == "uncacheable"


def test_uncacheability_propagates_downstream(cache_dir):
    add, calls = counting_task()
    with run_scope():
        record("producer", None, "uncacheable")
        consumer = add.cached(spec("consumer", deps={"a": ["producer"]}))
        consumer.call(1, 2)
        consumer.call(1, 2)
    assert len(calls) == 2


def test_unknown_dependency_is_treated_as_uncacheable(cache_dir):
    add, calls = counting_task()
    with run_scope():
        consumer = add.cached(spec("consumer", deps={"a": ["never-ran"]}))
        consumer.call(1, 2)
        consumer.call(1, 2)
    assert len(calls) == 2


# --- derivation through the DAG --------------------------------------------


def test_downstream_hits_when_upstream_identity_is_unchanged(cache_dir):
    add, calls = counting_task()
    consumer = add.cached(spec("consumer", deps={"a": ["producer"]}))
    for _ in range(2):
        with run_scope():
            record("producer", "sha256:same", "miss")
            consumer.call(1, 2)
    assert len(calls) == 1


def test_downstream_misses_when_upstream_identity_moves(cache_dir):
    add, calls = counting_task()
    consumer = add.cached(spec("consumer", deps={"a": ["producer"]}))
    for upstream in ("sha256:first", "sha256:second"):
        with run_scope():
            record("producer", upstream, "miss")
            consumer.call(1, 2)
    assert len(calls) == 2


def test_every_step_contributes_its_output_digest(cache_dir):
    # Not its own identity: the key below a step must answer "will this produce
    # the same output?", and only the digest does.
    add, _ = counting_task()
    with run_scope() as ids:
        s = spec("producer")
        add.cached(s).call(1, 2)
        assert ids["producer"].digest != step_identity(s)
        assert ids["producer"].digest.startswith("tree/v2/")


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

    consumer = transform.cached(spec("consumer", deps={"n": ["producer"]}))
    for run in (1, 2):
        with run_scope():
            # A changing param forces the producer itself to re-execute.
            produce.cached(spec("producer", params={"run": run})).call(run)
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

    consumer = transform.cached(spec("consumer", deps={"n": ["producer"]}))
    for run in (1, 2):
        with run_scope():
            produce.cached(spec("producer", params={"run": run})).call(run)
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
    consumer = add.cached(spec("consumer", deps={"n": ["producer"]}))
    for producer in (seven, also_seven):
        with run_scope():
            producer.cached(spec("producer", function=producer.func.__name__)).call()
            consumer.call(1, 2)
    assert len(calls) == 1


# --- opting out of being served -------------------------------------------


def test_an_unservable_step_always_executes(cache_dir):
    add, calls = counting_task()
    cached = add.cached(spec(servable=False))
    assert [cached.call(1, 2), cached.call(1, 2)] == [3, 3]
    assert len(calls) == 2


def test_an_unservable_step_stores_nothing(cache_dir):
    # Verify mode relies on this: a step already declared untrustworthy has no
    # baseline to compare against, so there is nothing to learn from it.
    add, _ = counting_task()
    add.cached(spec(servable=False)).call(1, 2)
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

    consumer = transform.cached(spec("consumer", deps={"n": ["producer"]}))
    for _ in range(2):
        with run_scope():
            produce.cached(spec("producer", servable=False)).call()
            consumer.call(42)

    assert producer_calls == [1, 1]  # never served
    assert consumer_calls == [42]  # but everything below it still hit


def test_an_unservable_step_promotes_its_output_digest(cache_dir):
    add, _ = counting_task()
    with run_scope() as ids:
        add.cached(spec("producer", servable=False)).call(1, 2)
        assert ids["producer"].digest.startswith("tree/v2/")


# --- verify mode -----------------------------------------------------------


@pytest.fixture
def verifying(monkeypatch):
    monkeypatch.setenv("WT_CACHE_VERIFY", "1")


def test_verify_mode_reports_a_nondeterministic_step_by_name(cache_dir, monkeypatch):
    results = iter([1, 2])

    @task
    def unstable() -> int:
        return next(results)

    cached = unstable.cached(spec("wobbly"))
    cached.call()  # the baseline run

    monkeypatch.setenv("WT_CACHE_VERIFY", "1")
    with pytest.warns(CacheMismatchWarning, match="'wobbly'"):
        assert cached.call() == 2  # the fresh value, not the stored one


def test_verify_mode_is_quiet_for_a_deterministic_step(cache_dir, monkeypatch):
    add, calls = counting_task()
    cached = add.cached(spec())
    cached.call(1, 2)

    monkeypatch.setenv("WT_CACHE_VERIFY", "1")
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

    cached = unstable.cached(spec("wobbly"))
    cached.call()
    stored = {p: p.read_bytes() for p in cache_dir.rglob("*") if p.is_file()}

    monkeypatch.setenv("WT_CACHE_VERIFY", "1")
    for _ in range(2):
        with pytest.warns(CacheMismatchWarning):
            cached.call()
    assert {p: p.read_bytes() for p in cache_dir.rglob("*") if p.is_file()} == stored


def test_verify_mode_skips_a_step_that_was_never_stored(cache_dir, verifying):
    add, _ = counting_task()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        add.cached(spec()).call(1, 2)
    assert [w for w in caught if issubclass(w.category, CacheMismatchWarning)] == []


def test_verify_mode_is_inert_without_a_store(monkeypatch):
    monkeypatch.delenv("WT_CACHE", raising=False)
    monkeypatch.setenv("WT_CACHE_VERIFY", "1")
    add, calls = counting_task()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert add.cached(spec()).call(1, 2) == 3
    assert caught == []
    assert len(calls) == 1


# --- values that must survive the round trip -------------------------------


def test_skip_sentinel_round_trips_through_the_store(cache_dir):
    calls = []

    @task
    def maybe(x: int) -> int:
        calls.append(x)
        return x

    cached = maybe.skipif([lambda *a: True]).cached(spec())
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
    def produce() -> object:
        return value

    cached = produce.cached(spec())
    assert cached.call() == value
    assert cached.call() == value


def test_bytes_round_trip(cache_dir):
    @task
    def produce() -> bytes:
        return b"\x00\x01binary"

    cached = produce.cached(
        spec(structure={"k": "ref", "ref": "wt_task.cache:BYTES", "type": None})
    )
    assert cached.call() == b"\x00\x01binary"
    assert cached.call() == b"\x00\x01binary"


# --- map and mapvalues cache as one step -----------------------------------


def test_map_caches_the_whole_step(cache_dir):
    calls = []

    @task
    def square(x: int) -> int:
        calls.append(x)
        return x * x

    cached = square.cached(spec(method="map"))
    assert cached.map("x", [1, 2, 3]) == [1, 4, 9]
    assert cached.map("x", [1, 2, 3]) == [1, 4, 9]
    assert calls == [1, 2, 3]  # one entry for the step, not one per item


def test_mapvalues_caches_the_whole_step(cache_dir):
    calls = []

    @task
    def double(x: int) -> int:
        calls.append(x)
        return x * 2

    cached = double.cached(spec(method="mapvalues"))
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

    cached = rename.cached(spec(method="mapvalues"))
    miss = cached.mapvalues("df", argvalues)
    hit = cached.mapvalues("df", argvalues)

    assert calls == ["a", "b"]  # the second call really was served
    assert hit == miss
    assert {k for k, _ in hit} == set(keys)  # hashable, and the same keys
    assert dict(hit) == {keys[0]: "A", keys[1]: "B"}


# --- failure handling ------------------------------------------------------


def test_a_corrupt_payload_fails_loudly(cache_dir):
    add, _ = counting_task()
    cached = add.cached(spec())
    cached.call(1, 2)

    payload = next(p for p in (cache_dir / "cas").rglob("*") if p.is_file())
    payload.write_bytes(b"not json at all")

    # Never a silent wrong value, and never a quiet recompute: the entry names an
    # installed codec and a payload that is present, so the store is lying.
    with pytest.raises(CacheCorruptionError):
        cached.call(1, 2)


def test_a_raising_task_stores_nothing(cache_dir):
    calls = []

    @task
    def boom() -> int:
        calls.append(1)
        raise ValueError("nope")

    cached = boom.cached(spec())
    for _ in range(2):
        with pytest.raises(ValueError):
            cached.call()
    assert len(calls) == 2


def test_an_unwritable_store_degrades_to_running(tmp_path, monkeypatch):
    unwritable = tmp_path / "ro"
    unwritable.mkdir()
    monkeypatch.setenv("WT_CACHE", str(unwritable))
    unwritable.chmod(0o500)
    try:
        add, calls = counting_task()
        cached = add.cached(spec())
        with pytest.warns(UserWarning, match="Could not write cache entry"):
            assert cached.call(1, 2) == 3
        assert len(calls) == 1
    finally:
        unwritable.chmod(0o700)


def test_argument_collecting_several_upstreams_folds_in_all_of_them(cache_dir):
    # `widgets: [${{ workflow.a.return }}, ${{ workflow.b.return }}]` binds one
    # argument to several steps; moving any of them must move the key.
    add, calls = counting_task()
    consumer = add.cached(spec("consumer", deps={"widgets": ["a", "b"]}))
    for b_identity in ("sha256:b1", "sha256:b1", "sha256:b2"):
        with run_scope():
            record("a", "sha256:a1", "miss")
            record("b", b_identity, "miss")
            consumer.call(1, 2)
    assert len(calls) == 2  # hit on the repeat, miss once `b` moved


def test_one_uncacheable_upstream_among_several_blocks_the_step(cache_dir):
    add, calls = counting_task()
    consumer = add.cached(spec("consumer", deps={"widgets": ["a", "b"]}))
    for _ in range(2):
        with run_scope():
            record("a", "sha256:a1", "miss")
            record("b", None, "uncacheable")
            consumer.call(1, 2)
    assert len(calls) == 2


# --- the structure the step actually returns -------------------------------


def test_a_mapped_step_wraps_the_declared_structure_in_a_list(cache_dir):
    @task
    def to_path(name: str) -> object:
        return Path("/var/data") / name

    structure = {"k": "ref", "ref": "wt_task.cache:PATH", "type": None}
    cached = to_path.cached(spec(structure=structure, method="map"))
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

    cached = double.skipif([lambda *a: a[0] < 0]).cached(spec(method="map"))
    first = cached.map("x", [1, -1, 3])
    second = cached.map("x", [1, -1, 3])
    assert [v for v in first if not isinstance(v, type(SKIP_SENTINEL))] == [2, 6]
    assert isinstance(second[1], type(SKIP_SENTINEL))
    assert calls == [1, 3]  # one entry for the step, served the second time


def test_a_declared_structure_the_value_does_not_fit_refuses(cache_dir):
    @task
    def produce() -> object:
        return object()

    structure = {"k": "ref", "ref": "wt_task.cache:BYTES", "type": None}
    cached = produce.cached(spec("producer", structure=structure))
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
    def unfitting() -> object:
        return object()

    bad_ref = {"k": "ref", "ref": "no_such_module_xyz:THING", "type": None}
    monkeypatch.delenv("WT_CACHE_STRICT", raising=False)
    with pytest.warns(UserWarning, match="could not be resolved"):
        unimportable = add.cached(spec("unimportable", structure=bad_ref))

    add.cached(spec("warm")).call(1, 2)  # a baseline to hit on

    with run_scope():
        add.cached(spec("warm")).call(1, 2)
        add.cached(spec("cold", params={"n": 1})).call(3, 4)
        add.cached(spec("unservable", servable=False)).call(5, 6)
        unknown.cached(spec("unknown", structure=None)).call()
        with pytest.warns(UserWarning, match="Not caching"):
            unfitting.cached(
                spec(
                    "unfitting",
                    structure={"k": "ref", "ref": "wt_task.cache:BYTES", "type": None},
                )
            ).call()
        unimportable.call(7, 8)
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
    monkeypatch.delenv("WT_CACHE", raising=False)
    add, _ = counting_task()
    with run_scope():
        add.cached(spec()).call(1, 2)
        assert run_report()["step"]["outcome"] == "inert"


def test_the_run_report_names_the_upstream_that_blocked_a_step(cache_dir):
    add, _ = counting_task()
    with run_scope():
        record("producer", None, "uncacheable")
        add.cached(spec("consumer", deps={"a": ["producer"]})).call(1, 2)
        assert run_report()["consumer"]["reason"] == "upstream 'producer' uncacheable"


def test_the_run_report_survives_the_scope_that_produced_it(cache_dir):
    # The generated CLI builds its envelope after the DAG's scope has closed.
    add, _ = counting_task()
    with run_scope():
        add.cached(spec("only")).call(1, 2)
    assert run_report()["only"]["outcome"] == "miss"
