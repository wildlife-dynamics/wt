"""Tests for `WT_CACHE__IO_TTL`: how long an io step's result may be served."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from wt_task import task
from wt_task.cache import CacheEntry, CacheSpec, _key, _runtime, run_report, run_scope
from wt_task.cache._key import _packages_distributions, distribution_fingerprint
from wt_task.cache._settings import ENV_PREFIX, CacheSettings, load_settings, parse_duration

IO_TTL_ENV_VAR = f"{ENV_PREFIX}IO_TTL"

ANCHOR = "test_io_ttl"


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_CACHE__STORE", str(tmp_path / "cache"))
    for var in ("WT_CACHE__EPOCH", "WT_CACHE__SCOPE", "WT_CACHE__VERIFY", IO_TTL_ENV_VAR):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("WT_CACHE__STRICT", "1")
    # An io step with no scope is never served; these tests are about the TTL.
    monkeypatch.setenv("WT_CACHE__SCOPE", "tenant-a")

    real = _packages_distributions()
    monkeypatch.setattr(_key, "_packages_distributions", lambda: {**real, ANCHOR: ["wt-task"]})
    distribution_fingerprint.cache_clear()
    yield tmp_path / "cache"
    distribution_fingerprint.cache_clear()


def source(task_instance_id="source", **kwargs):
    """An io-tagged step: the only kind the TTL applies to."""
    kwargs.setdefault("signature", "signature-1")
    kwargs.setdefault("scoped", True)
    return CacheSpec(**kwargs)


def fetching_task():
    calls = []

    @task
    def fetch() -> int:
        calls.append(1)
        return 42

    return fetch, calls


def age_the_entry(cache_dir, by):
    """Backdate every stored entry, instead of waiting for the clock.

    Every entry, so that a DAG's derived steps age too — which is exactly the
    case that must stay unaffected.
    """
    for path in (cache_dir / "keys").rglob("*"):
        if not path.is_file():
            continue
        entry = CacheEntry.model_validate_json(path.read_bytes())
        aged = entry.model_copy(update={"created_at": entry.created_at - by})
        path.write_bytes(aged.model_dump_json().encode())


# --- parsing ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", None),
        ("forever", None),
        ("FOREVER", None),
        ("  forever  ", None),
        ("never", timedelta(0)),
        ("0", timedelta(0)),
        ("90", timedelta(seconds=90)),
        ("45s", timedelta(seconds=45)),
        ("30m", timedelta(minutes=30)),
        ("1h", timedelta(hours=1)),
        ("7d", timedelta(days=7)),
    ],
)
def test_durations_parse(raw, expected):
    assert parse_duration(raw) == expected


@pytest.mark.parametrize("raw", ["soon", "-5", "1w", "1.5h", "h", "1 h", "30mm"])
def test_bad_durations_are_rejected(raw):
    with pytest.raises(ValueError, match="expected"):
        parse_duration(raw)


def test_a_bad_value_fails_safe_towards_freshness(monkeypatch):
    # Costs a refetch, but never serves something older than was asked for.
    monkeypatch.delenv("WT_CACHE__STRICT", raising=False)
    monkeypatch.setenv(IO_TTL_ENV_VAR, "soon")
    with pytest.warns(UserWarning, match="Ignoring unusable cache settings"):
        assert load_settings().io_ttl == timedelta(0)


def test_a_bad_value_raises_under_strict_mode(monkeypatch):
    monkeypatch.setenv("WT_CACHE__STRICT", "1")
    monkeypatch.setenv(IO_TTL_ENV_VAR, "soon")
    with pytest.raises(ValidationError):
        load_settings()


def test_the_settings_are_read_once_per_run(cache_dir, monkeypatch):
    # Changing the environment mid-run must not take effect until the next
    # scope, or two steps of one DAG could disagree about the policy.
    monkeypatch.setenv(IO_TTL_ENV_VAR, "forever")
    fetch, calls = fetching_task()
    cached = fetch.set_task_instance_id("source").cached(source())

    with run_scope():
        cached.call()
        age_the_entry(cache_dir, timedelta(days=365))
        monkeypatch.setenv(IO_TTL_ENV_VAR, "never")
        cached.call()
    assert len(calls) == 1  # still on the settings this scope opened with

    with run_scope():
        cached.call()
    assert len(calls) == 2  # the next scope picks the change up


def test_explicit_settings_win_over_the_environment(cache_dir, monkeypatch):
    monkeypatch.setenv(IO_TTL_ENV_VAR, "forever")
    fetch, calls = fetching_task()
    cached = fetch.set_task_instance_id("source").cached(source())

    with run_scope():
        cached.call()
    with run_scope(settings=CacheSettings(store=str(cache_dir), io_ttl="never")):
        cached.call()
    assert len(calls) == 2


# --- serving ----------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "forever"])
def test_an_old_entry_is_served_indefinitely_by_default(cache_dir, monkeypatch, value):
    if value is None:
        monkeypatch.delenv(IO_TTL_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(IO_TTL_ENV_VAR, value)
    fetch, calls = fetching_task()
    cached = fetch.set_task_instance_id("source").cached(source())

    cached.call()
    age_the_entry(cache_dir, timedelta(days=365))
    assert cached.call() == 42
    assert len(calls) == 1


@pytest.mark.parametrize("value", ["never", "0"])
def test_never_always_refetches(cache_dir, monkeypatch, value):
    monkeypatch.setenv(IO_TTL_ENV_VAR, value)
    fetch, calls = fetching_task()
    cached = fetch.set_task_instance_id("source").cached(source())
    cached.call()
    cached.call()
    assert len(calls) == 2


def test_never_still_writes_so_it_acts_as_a_force_refresh(cache_dir, monkeypatch):
    fetch, calls = fetching_task()
    cached = fetch.set_task_instance_id("source").cached(source())

    monkeypatch.setenv(IO_TTL_ENV_VAR, "never")
    cached.call()
    assert len(calls) == 1

    # A later run with a TTL uses what the refresh wrote.
    monkeypatch.setenv(IO_TTL_ENV_VAR, "forever")
    assert cached.call() == 42
    assert len(calls) == 1


def test_a_fresh_entry_is_served_and_a_stale_one_is_not(cache_dir, monkeypatch):
    monkeypatch.setenv(IO_TTL_ENV_VAR, "1h")
    fetch, calls = fetching_task()
    cached = fetch.set_task_instance_id("source").cached(source())

    cached.call()
    age_the_entry(cache_dir, timedelta(minutes=30))
    cached.call()
    assert len(calls) == 1  # still fresh

    age_the_entry(cache_dir, timedelta(hours=2))
    cached.call()
    assert len(calls) == 2  # expired


def test_an_expired_entry_is_overwritten(cache_dir, monkeypatch):
    monkeypatch.setenv(IO_TTL_ENV_VAR, "1h")
    fetch, _ = fetching_task()
    cached = fetch.set_task_instance_id("source").cached(source())
    cached.call()
    age_the_entry(cache_dir, timedelta(hours=2))

    before = next(p for p in (cache_dir / "keys").rglob("*") if p.is_file())
    stale = CacheEntry.model_validate_json(before.read_bytes()).created_at
    cached.call()
    refreshed = CacheEntry.model_validate_json(before.read_bytes()).created_at
    assert refreshed > stale


def test_an_expired_entry_costs_no_payload_read(cache_dir, monkeypatch):
    # Freshness is judged from the entry, before the payload is fetched.
    monkeypatch.setenv(IO_TTL_ENV_VAR, "1h")
    fetch, _ = fetching_task()
    cached = fetch.set_task_instance_id("source").cached(source())
    cached.call()
    age_the_entry(cache_dir, timedelta(hours=2))

    reads = []
    real = _runtime.CONTENT_PREFIX
    monkeypatch.setattr(
        _runtime,
        "_path",
        lambda prefix, name: (
            reads.append(prefix) if prefix == real else None,
            f"{prefix}/{name}",
        )[1],
    )
    cached.call()
    assert reads == [real]  # the write, not a read


# --- derived steps do not age ----------------------------------------------


def test_a_derived_step_is_unaffected_by_any_ttl(cache_dir, monkeypatch):
    monkeypatch.setenv(IO_TTL_ENV_VAR, "never")
    fetch, calls = fetching_task()
    derived = fetch.set_task_instance_id("derived").cached(source(scoped=False))
    derived.call()
    age_the_entry(cache_dir, timedelta(days=365))
    derived.call()
    assert len(calls) == 1


# --- early cutoff -----------------------------------------------------------


def test_a_refetch_of_identical_content_still_cuts_off_downstream(cache_dir, monkeypatch):
    monkeypatch.setenv(IO_TTL_ENV_VAR, "1h")
    source_calls = []
    derived_calls = []

    @task
    def read_world() -> int:
        source_calls.append(1)
        return 42  # the same content, refetched

    @task
    def transform(n: int) -> int:
        derived_calls.append(n)
        return n * 2

    src = read_world.set_task_instance_id("source").cached(source())
    downstream = transform.set_task_instance_id("derived").cached(
        source("derived", scoped=False, upstream_inputs={"n": ["source"]})
    )

    with run_scope():
        src.call()
        downstream.call(42)

    age_the_entry(cache_dir, timedelta(hours=2))

    with run_scope() as ids:
        src.call()
        downstream.call(42)
        outcomes = (ids["source"].outcome, ids["derived"].outcome)

    assert source_calls == [1, 1]  # the source refetched
    assert derived_calls == [42]  # but the step below it hit
    assert outcomes == ("expired", "hit")


# --- the run report ---------------------------------------------------------


def test_the_report_distinguishes_an_expiry_from_an_always_refetch(cache_dir, monkeypatch):
    fetch, _ = fetching_task()
    cached = fetch.set_task_instance_id("source").cached(source())

    monkeypatch.setenv(IO_TTL_ENV_VAR, "1h")
    cached.call()
    age_the_entry(cache_dir, timedelta(hours=2))
    with run_scope():
        cached.call()
        aged = run_report()["source"]

    monkeypatch.setenv(IO_TTL_ENV_VAR, "never")
    with run_scope():
        cached.call()
        always = run_report()["source"]

    assert aged["outcome"] == always["outcome"] == "expired"
    assert aged["reason"] == "older than 3600s (age 7200s)"
    assert always["reason"] == f"{IO_TTL_ENV_VAR} is zero: io steps always refetch"
    # An expired step still promotes its digest, which is what lets the steps
    # below it hit.
    assert aged["digest"] == always["digest"]


def test_a_served_step_still_reports_a_hit(cache_dir, monkeypatch):
    monkeypatch.setenv(IO_TTL_ENV_VAR, "1h")
    fetch, _ = fetching_task()
    cached = fetch.set_task_instance_id("source").cached(source())
    cached.call()
    with run_scope():
        cached.call()
        assert run_report()["source"]["outcome"] == "hit"


# --- verify mode is unchanged ----------------------------------------------


def test_verify_mode_keeps_its_semantics_under_a_ttl(cache_dir, monkeypatch):
    monkeypatch.setenv(IO_TTL_ENV_VAR, "1h")
    fetch, calls = fetching_task()
    cached = fetch.set_task_instance_id("source").cached(source())
    cached.call()
    stored = {p: p.read_bytes() for p in cache_dir.rglob("*") if p.is_file()}

    monkeypatch.setenv("WT_CACHE__VERIFY", "1")
    with run_scope():
        cached.call()
        assert run_report()["source"]["outcome"] == "miss"
    assert len(calls) == 2  # verify executes everything
    assert {p: p.read_bytes() for p in cache_dir.rglob("*") if p.is_file()} == stored
