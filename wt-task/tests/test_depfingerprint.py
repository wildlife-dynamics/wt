"""Tests for the dependency-closure half of a step's code identity."""

import importlib.metadata

import pytest

from wt_task.cache import _key
from wt_task.cache._key import (
    _closure_fingerprint,
    _extra_is_installed,
    _packages_distributions,
    distribution_version,
)


class FakeDistribution(importlib.metadata.Distribution):
    """An installed distribution whose METADATA is built from its fields."""

    def __init__(self, name, version, requires, extras):
        self._name = name
        lines = ["Metadata-Version: 2.1", f"Name: {name}", f"Version: {version}"]
        lines += [f"Requires-Dist: {req}" for req in requires]
        lines += [f"Provides-Extra: {extra}" for extra in extras]
        self._text = "\n".join(lines) + "\n"

    def read_text(self, filename):
        return self._text if filename == "METADATA" else None

    def locate_file(self, path):
        raise NotImplementedError

    @property
    def _normalized_name(self):
        return self._name


CACHES = (
    _key._index,
    _key._requirements,
    _key._gated_requirements,
    _closure_fingerprint,
    _extra_is_installed,
    distribution_version,
)


def clear_caches():
    for cached in CACHES:
        cached.cache_clear()


@pytest.fixture
def world(monkeypatch):
    """Install a fake distribution set, and point the walk at it.

    Each entry is `name -> (version, [requirement strings], [extra names])`.
    """

    def install(dists, top_level=None):
        fakes = [FakeDistribution(name, *fields) for name, fields in dists.items()]
        monkeypatch.setattr(importlib.metadata, "distributions", lambda: iter(fakes))
        monkeypatch.setattr(_key, "_packages_distributions", lambda: top_level or {"app": ["app"]})
        clear_caches()

    yield install
    clear_caches()


def dists(**overrides):
    """A small app whose dependency tree mirrors the real shape."""
    base = {
        "app": ("1.0", ["lib>=1", "optional-thing; extra == 'gcp'"], ["gcp"]),
        "lib": ("2.0", ["deep"], []),
        "deep": ("3.0", [], []),
    }
    base.update(overrides)
    return base


# --- stability --------------------------------------------------------------


def test_the_fingerprint_is_stable_across_calls(world):
    world(dists())
    first = distribution_version("app")
    _closure_fingerprint.cache_clear()
    assert distribution_version.__wrapped__("app") == first


def test_the_walk_runs_at_most_once_per_distribution(world, monkeypatch):
    world(dists())
    calls = []
    real = _key._requirements
    monkeypatch.setattr(_key, "_requirements", lambda n: (calls.append(n), real(n))[1])
    distribution_version("app")
    after_first = len(calls)

    # Every later step, and every other module of the same distribution, reads
    # the memoised answer rather than walking again.
    for _ in range(5):
        distribution_version("app")
        distribution_version(f"app.submodule{_}")
    assert len(calls) == after_first


# --- what moves it, and what does not --------------------------------------


def test_a_transitive_dependency_version_moves_the_fingerprint(world):
    world(dists())
    before = distribution_version("app")

    world(dists(deep=("3.1", [], [])))
    after = distribution_version("app")

    assert before != after
    # Only the closure digest moved; the task's own distribution did not.
    assert before.split("+deps:")[0] == after.split("+deps:")[0] == "app==1.0"


def test_a_direct_dependency_version_moves_the_fingerprint(world):
    world(dists())
    before = distribution_version("app")
    world(dists(lib=("2.1", ["deep"], [])))
    assert distribution_version("app") != before


def test_an_unrelated_installed_distribution_does_not_move_it(world):
    world(dists())
    before = distribution_version("app")
    world(dists(elsewhere=("9.9", [], [])))
    assert distribution_version("app") == before


def test_the_string_still_starts_with_the_distributions_own_version(world):
    world(dists())
    identity = distribution_version("app")
    assert identity.startswith("app==1.0+deps:")
    assert len(identity.split("+deps:")[1]) == 12


def test_several_distributions_for_one_module_are_all_named(world):
    world(
        {**dists(), "sibling": ("0.5", [], [])},
        top_level={"app": ["sibling", "app"]},
    )
    assert distribution_version("app").startswith("app==1.0;sibling==0.5+deps:")


# --- optional dependencies --------------------------------------------------


def test_an_uninstalled_optional_dependency_is_ignored(world):
    # `optional-thing` is gated on an extra and is not installed, so the walk
    # skips it rather than failing — declaring an extra you have not installed
    # has to leave the fingerprint exactly where it was.
    world(dists())
    declared_but_absent = distribution_version("app")

    world({**dists(), "app": ("1.0", ["lib>=1"], [])})
    assert distribution_version("app") == declared_but_absent


def test_an_installed_extra_is_followed(world):
    world(dists())
    without = distribution_version("app")

    world({**dists(), "optional-thing": ("7.0", [], [])})
    assert distribution_version("app") != without


def test_a_half_installed_extra_is_not_followed(world):
    # The rule is "all of the extra's requirements are installed"; one of two
    # present means the extra is not in use here.
    two = {
        "app": (
            "1.0",
            ["a; extra == 'bundle'", "b; extra == 'bundle'"],
            ["bundle"],
        ),
        "a": ("1.0", [], []),
    }
    world(two)
    assert _extra_is_installed("app", "bundle") is False
    half = distribution_version("app")

    world({**two, "b": ("1.0", [], [])})
    assert _extra_is_installed("app", "bundle") is True
    assert distribution_version("app") != half


def test_a_requirement_whose_marker_excludes_this_environment_is_skipped(world):
    world(
        {
            "app": ("1.0", ["lib>=1", "windows-only; sys_platform == 'win32'"], []),
            "lib": ("2.0", ["deep"], []),
            "deep": ("3.0", [], []),
            "windows-only": ("4.0", [], []),
        }
    )
    without_marker = distribution_version("app")
    world(dists())
    assert distribution_version("app") == without_marker


# --- failing closed ---------------------------------------------------------


def test_a_cycle_terminates(world):
    world({"app": ("1.0", ["lib"], []), "lib": ("2.0", ["app"], [])})
    assert distribution_version("app").startswith("app==1.0+deps:")


def test_unreadable_metadata_means_do_not_cache(world, monkeypatch):
    world(dists())

    def boom(_self):
        raise RuntimeError("metadata is unreadable")

    monkeypatch.setattr(FakeDistribution, "metadata", property(boom))
    clear_caches()
    with pytest.warns(UserWarning, match="Could not fingerprint"):
        assert distribution_version("app") is None


def test_a_module_belonging_to_no_distribution_is_not_cached():
    assert distribution_version("no_such_distribution_xyz") is None


# --- against the real environment -------------------------------------------


def test_the_real_fingerprint_covers_this_package_and_its_closure():
    assert "wt_task" in _packages_distributions()
    identity = distribution_version("wt_task")
    own, _, digest = identity.partition("+deps:")
    assert own.startswith("wt-task==")
    assert len(digest) == 12


def test_metadata_unreadable_without_even_a_name_means_do_not_cache(world, monkeypatch):
    world(dists())
    monkeypatch.setattr(FakeDistribution, "metadata", property(lambda _self: 1 / 0))
    monkeypatch.setattr(FakeDistribution, "_normalized_name", None)
    clear_caches()
    with pytest.warns(UserWarning, match="ZeroDivisionError"):
        assert distribution_version("app") is None


def test_an_unreadable_distribution_outside_the_closure_does_not_matter(world, monkeypatch):
    world(dists(elsewhere=("9.9", [], [])))
    before = distribution_version("app")

    real = FakeDistribution.metadata

    def metadata(self):
        if self._name == "elsewhere":
            raise RuntimeError("metadata is unreadable")
        return real.fget(self)

    monkeypatch.setattr(FakeDistribution, "metadata", property(metadata))
    clear_caches()
    assert distribution_version("app") == before


# --- cost: one metadata pass per process ------------------------------------


@pytest.fixture
def fresh_index():
    _packages_distributions.cache_clear()
    clear_caches()
    yield
    _packages_distributions.cache_clear()
    clear_caches()


ANCHORS = ["wt_task", "wt_task.cache", "pydantic", "packaging.requirements", "wt_contracts"]


def test_the_index_is_built_once_per_process(fresh_index, monkeypatch):
    calls = []
    real = importlib.metadata.distributions
    monkeypatch.setattr(
        importlib.metadata, "distributions", lambda **kw: (calls.append(kw), real(**kw))[1]
    )
    for _ in range(3):
        for anchor in ANCHORS:
            assert distribution_version(anchor) is not None
        # Force the walk itself to rerun; only the metadata pass is shared.
        _closure_fingerprint.cache_clear()
        _extra_is_installed.cache_clear()
        distribution_version.cache_clear()
    assert calls == [{}]


def test_the_walk_makes_no_per_name_metadata_calls(fresh_index, monkeypatch):
    calls = []
    for name in ("distribution", "version", "requires", "metadata", "packages_distributions"):
        real = getattr(importlib.metadata, name)
        monkeypatch.setattr(
            importlib.metadata,
            name,
            lambda *a, _n=name, _r=real, **kw: (calls.append(_n), _r(*a, **kw))[1],
        )
    for anchor in ANCHORS:
        assert distribution_version(anchor) is not None
    assert calls == []


def test_the_lazy_top_level_map_agrees_with_the_stdlibs(fresh_index):
    full = importlib.metadata.packages_distributions()
    lazy = _packages_distributions()
    assert {k: sorted(set(lazy[k])) for k in full} == {k: sorted(set(v)) for k, v in full.items()}
    assert "no_such_module_xyz" not in lazy


def test_without_per_distribution_helpers_the_full_map_is_used(fresh_index, monkeypatch):
    monkeypatch.setattr(_key, "_TOP_LEVEL_DECLARED", None)
    assert (
        _packages_distributions()["wt_task"]
        == importlib.metadata.packages_distributions()["wt_task"]
    )


def test_egg_info_requirements_are_followed(world, monkeypatch):
    # No Requires-Dist in the metadata: requirements live in requires.txt.
    world({"app": ("1.0", [], []), "deep": ("3.0", [], [])})
    alone = distribution_version("app")

    real = FakeDistribution.read_text
    monkeypatch.setattr(
        FakeDistribution,
        "read_text",
        lambda self, f: "deep\n" if (self._name, f) == ("app", "requires.txt") else real(self, f),
    )
    clear_caches()
    via_requires_txt = distribution_version("app")

    monkeypatch.setattr(FakeDistribution, "read_text", real)
    world({"app": ("1.0", ["deep"], []), "deep": ("3.0", [], [])})
    assert via_requires_txt == distribution_version("app") != alone
