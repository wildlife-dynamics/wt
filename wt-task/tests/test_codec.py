"""Tests for the builtin leaf codecs and for resolving declared structures."""

import enum
import pathlib

import pytest
from pydantic_core import Url

from wt_task.cache import BYTES, JSON, PATH, SKIP, URL, Codec, Undigestible, enum_codec
from wt_task.cache._codec import json_digest
from wt_task.cache._tree import resolve_structure
from wt_task.skip import SKIP_SENTINEL


class Unit(enum.Enum):
    km = "km"
    mi = "mi"


def ref(path, type_=None):
    return {"k": "ref", "ref": path, "type": type_}


@pytest.fixture(autouse=True)
def strict(monkeypatch):
    # Resolution failures degrade on a deployed service; in tests they must shout.
    monkeypatch.setenv("WT_CACHE_STRICT", "1")


# --- builtin leaves --------------------------------------------------------


@pytest.mark.parametrize(
    ("codec", "value"),
    [
        (BYTES, b"\x00\x01binary"),
        (PATH, pathlib.Path("/var/data/x.parquet")),
        (URL, Url("https://example.com/a")),
        (JSON, {"a": [1, None, True]}),
        (enum_codec(Unit), Unit.km),
    ],
)
def test_builtin_leaves_round_trip(codec, value):
    assert codec.decode(codec.encode(value)) == value


def test_the_skip_sentinel_round_trips_to_the_same_object():
    assert SKIP.decode(SKIP.encode(SKIP_SENTINEL)) is SKIP_SENTINEL


def test_digests_are_stable_and_content_sensitive():
    assert BYTES.digest(b"a") == BYTES.digest(b"a")
    assert BYTES.digest(b"a") != BYTES.digest(b"b")
    assert JSON.digest({"a": 1, "b": 2}) == JSON.digest({"b": 2, "a": 1})


def test_the_json_codec_declines_what_json_cannot_hold():
    # The point of dropping `default=str`: a value that is not JSON refuses to
    # be cached rather than being silently stringified.
    with pytest.raises(Undigestible):
        JSON.digest({"when": object()})


def test_an_enum_codec_is_exact_and_names_its_class():
    codec = enum_codec(Unit)
    assert codec.exact is True
    assert codec.types == (Unit,)
    assert Unit.__qualname__ in codec.codec_id


def test_json_digest_is_key_order_independent():
    assert json_digest({"b": 1, "a": 2}) == json_digest({"a": 2, "b": 1})
    assert json_digest({"a": 1}) != json_digest({"a": 2})


# --- resolving a declared structure ---------------------------------------


def test_resolve_structure_handles_every_node_kind():
    structure = {
        "k": "dataclass",
        "type": "wt_task.cache._entry:CacheEntry",
        "fields": {},
    }
    assert resolve_structure(structure) is not None

    for node in (
        {"k": "json"},
        {"k": "dynamic"},
        ref("wt_task.cache:BYTES"),
        ref("wt_task.cache:enum_codec", "test_codec:Unit"),
        {"k": "list", "of": {"k": "json"}},
        {"k": "list", "tuple": True, "of": {"k": "json"}},
        {"k": "tuple", "of": [{"k": "json"}, ref("wt_task.cache:PATH")]},
        {"k": "dict", "key": {"k": "json"}, "of": {"k": "json"}},
        {"k": "union", "of": [{"k": "json"}, ref("wt_task.cache:SKIP")]},
    ):
        assert resolve_structure(node).codec_id == "tree/v2"


def test_resolve_structure_is_inert_for_an_undeclared_return():
    assert resolve_structure(None) is None


def test_a_class_parameterized_ref_is_called_with_the_named_class():
    tree = resolve_structure(ref("wt_task.cache:enum_codec", "test_codec:Unit"))
    assert tree.decode(tree.encode(Unit.mi)) is Unit.mi


@pytest.mark.parametrize(
    "structure",
    [
        ref("no_such_module_xyz:THING"),
        ref("wt_task.cache:NO_SUCH_CODEC"),
        ref("wt_task.cache:enum_codec", "wt_task.cache:NoSuchClass"),
    ],
)
def test_an_unresolvable_ref_raises_under_strict_mode(structure):
    with pytest.raises(ImportError):
        resolve_structure(structure)


def test_an_unknown_node_kind_is_rejected():
    with pytest.raises(ValueError, match="Unknown cache structure node"):
        resolve_structure({"k": "mystery"})


def test_an_unresolvable_ref_degrades_to_uncacheable_when_not_strict(monkeypatch):
    # In the executor the environment that compiled a spec and the one running
    # it can skew, and caching must never fail a run.
    monkeypatch.delenv("WT_CACHE_STRICT", raising=False)
    with pytest.warns(UserWarning, match="could not be resolved"):
        assert resolve_structure(ref("no_such_module_xyz:THING")) is None


# --- exactness -------------------------------------------------------------


class Base:
    pass


class Derived(Base):
    pass


def base_codec(cls):
    return Codec(
        codec_id="base/v1",
        media_type="text/plain",
        types=(cls,),
        encode=lambda _v: b"",
        decode=lambda _d: cls(),
        digest=lambda _v: "constant",
        exact=True,
    )


def test_an_exact_arm_rejects_a_subclass():
    # A field annotated with a base class and returned as a subclass is
    # reported cacheable and refused here; the fix is a narrower annotation.
    tree = resolve_structure(ref("test_codec:base_codec", "test_codec:Base"))
    assert tree.digest(Base())
    with pytest.raises(Undigestible):
        tree.digest(Derived())


def test_a_non_exact_codec_accepts_a_subclass():
    class MyPath(pathlib.PurePosixPath):
        pass

    assert PATH.exact is False
    tree = resolve_structure(ref("wt_task.cache:PATH"))
    assert tree.digest(MyPath("/a/b"))
