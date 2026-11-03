"""Tests for the per-run cache report written beside result.json."""

import json

import pytest

from wt_task import task
from wt_task.cache import (
    REPORT_NAME,
    CacheSettings,
    CacheSpec,
    _key,
    cache_report,
    put_cache_report,
    record,
    run_scope,
)
from wt_task.cache._key import _packages_distributions, distribution_fingerprint

ANCHOR = "test_report"


@pytest.fixture(autouse=True)
def tasks_belong_to_a_distribution(monkeypatch):
    real = _packages_distributions()
    monkeypatch.setattr(_key, "_packages_distributions", lambda: {**real, ANCHOR: ["wt-task"]})
    distribution_fingerprint.cache_clear()
    yield
    distribution_fingerprint.cache_clear()


@pytest.fixture
def store_settings(tmp_path):
    return CacheSettings(store=str(tmp_path / "cache"), strict=True)


class DictStore(dict):
    def put(self, key, data):
        self[key] = data


@task
def add(a: int, b: int) -> int:
    return a + b


@task
def boom() -> int:
    raise ValueError("nope")


def step(t, task_instance_id):
    return t.set_task_instance_id(task_instance_id).handle_errors().cached(CacheSpec("sig"))


def test_a_completed_run(store_settings):
    with run_scope(settings=store_settings):
        step(add, "a").call(1, 2)
        step(add, "b").call(1, 2)
    report = cache_report()

    assert report["status"] == "completed"
    assert "error" not in report
    assert "failed_step" not in report
    assert report["summary"] == {"hit": 1, "miss": 1}
    assert report["steps"]["a"]["outcome"] == "miss"
    assert set(report["steps"]["a"]) == {"digest", "outcome", "reason", "ms"}


def test_a_failed_run_keeps_the_rows_before_the_failure_and_names_the_step(store_settings):
    def dag():
        with run_scope(settings=store_settings):
            step(add, "first").call(1, 2)
            step(boom, "broken").call()
            step(add, "never").call(3, 4)

    with pytest.raises(Exception, match="nope"):
        dag()
    report = cache_report()

    assert report["status"] == "failed"
    assert report["failed_step"] == "broken"
    assert report["error"] == "Task instance 'broken' raised ValueError('nope')"
    assert list(report["steps"]) == ["first"]
    assert report["summary"] == {"miss": 1}


def test_a_failure_from_no_known_step_has_no_failed_step(store_settings):
    with pytest.raises(RuntimeError), run_scope(settings=store_settings):
        raise RuntimeError("before any step")
    report = cache_report()
    assert report["status"] == "failed"
    assert report["error"] == "before any step"
    assert "failed_step" not in report


def test_an_error_the_scope_did_not_see_still_fails_the_report(store_settings):
    with run_scope(settings=store_settings):
        step(add, "a").call(1, 2)
    report = cache_report(error="result is not JSON-serializable")
    assert report["status"] == "failed"
    assert report["error"] == "result is not JSON-serializable"
    assert list(report["steps"]) == ["a"]


def test_inside_a_scope_the_run_is_still_running(store_settings):
    with run_scope(settings=store_settings):
        record("a", None, "inert")
        assert cache_report()["status"] == "running"


def test_the_settings_block_is_redacted():
    secret = CacheSettings(
        store="gs://private-bucket/tenant-42/cache",
        epoch="build-sha-123",
        scope="token-digest-456",
        io_ttl="30m",
        verify=True,
    )
    with run_scope(settings=secret):
        pass
    report = cache_report()

    assert report["settings"] == {
        "store": {"configured": True, "scheme": "gs"},
        "io_ttl": "1800s",
        "verify": True,
        "strict": False,
        "epoch_set": True,
        "scope_set": True,
    }
    text = json.dumps(report)
    for value in ("private-bucket", "tenant-42", "build-sha-123", "token-digest-456"):
        assert value not in text


@pytest.mark.parametrize(
    ("store", "scheme"),
    [("", None), ("cache-dir", "file"), ("file:///srv/cache", "file"), ("s3://b/p", "s3")],
)
def test_the_store_scheme(store, scheme):
    with run_scope(settings=CacheSettings(store=store)):
        pass
    assert cache_report()["settings"]["store"] == {"configured": bool(store), "scheme": scheme}


@pytest.mark.parametrize(
    ("ttl", "rendered"), [(None, "forever"), ("never", "never"), ("90", "90s")]
)
def test_io_ttl_is_reported_as_configured(ttl, rendered):
    with run_scope(settings=CacheSettings(io_ttl=ttl)):
        pass
    assert cache_report()["settings"]["io_ttl"] == rendered


def test_put_writes_the_report_as_json(store_settings):
    with run_scope(settings=store_settings):
        step(add, "a").call(1, 2)
    store = DictStore()
    assert put_cache_report(store) is True
    assert json.loads(store[REPORT_NAME]) == cache_report()


def test_a_store_that_will_not_write_only_warns():
    class Broken:
        def put(self, key, data):
            raise OSError("read-only")

    with pytest.warns(UserWarning, match="Could not write cache-report.json"):
        assert put_cache_report(Broken()) is False
