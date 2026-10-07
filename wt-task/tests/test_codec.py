"""Tests for the cache codec registry."""

import pytest

from wt_task.cache import Codec, CodecConflictError
from wt_task.cache._codec import BUILTIN_CODECS, build_registry, json_digest
from wt_task.skip import SKIP_SENTINEL


def _codec(codec_id, types, priority=0, matches=None):
    return Codec(
        codec_id=codec_id,
        media_type="application/x-test",
        types=types,
        encode=lambda v: repr(v).encode(),
        decode=lambda d: d.decode(),
        digest=lambda v: repr(v),
        matches=matches,
        priority=priority,
    )


@pytest.fixture
def registry():
    return build_registry(BUILTIN_CODECS)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"a": 1}, "json/v1"),
        ([1, 2], "json/v1"),
        ("s", "json/v1"),
        (1, "json/v1"),
        (True, "json/v1"),
        (1.5, "json/v1"),
        (None, "json/v1"),
        (b"bytes", "bytes/v1"),
        (SKIP_SENTINEL, "skip/v1"),
    ],
)
def test_builtin_codecs_claim_their_types(registry, value, expected):
    assert registry.for_value(value).codec_id == expected


def test_unclaimed_type_is_refused_not_guessed(registry):
    # The whole no-pickle policy rests on this: an unknown type yields no codec,
    # and the caller runs the step instead of inventing an encoding.
    assert registry.for_value(object()) is None


def test_for_id_round_trips_and_misses_cleanly(registry):
    assert registry.for_id("json/v1").media_type == "application/json"
    assert registry.for_id("not-installed") is None


def test_duplicate_codec_id_is_rejected():
    with pytest.raises(CodecConflictError, match="Duplicate codec_id"):
        build_registry([*BUILTIN_CODECS, _codec("json/v1", ())])


def test_two_codecs_claiming_one_type_at_equal_priority_is_rejected():
    with pytest.raises(CodecConflictError, match="both claim"):
        build_registry([_codec("a", (str,)), _codec("b", (str,))])


def test_higher_priority_wins_over_a_builtin():
    reg = build_registry([*BUILTIN_CODECS, _codec("custom", (str,), priority=10)])
    assert reg.for_value("s").codec_id == "custom"
    # Unrelated types are untouched by the override.
    assert reg.for_value(1).codec_id == "json/v1"


def test_subclasses_dispatch_to_the_base_codec():
    class MyList(list):
        pass

    assert build_registry(BUILTIN_CODECS).for_value(MyList([1])).codec_id == "json/v1"


def test_skip_sentinel_round_trips_identically(registry):
    codec = registry.for_value(SKIP_SENTINEL)
    assert codec.decode(codec.encode(SKIP_SENTINEL)) is SKIP_SENTINEL


def test_json_digest_is_key_order_independent():
    assert json_digest({"b": 1, "a": 2}) == json_digest({"a": 2, "b": 1})


def test_json_digest_separates_different_content():
    assert json_digest({"a": 1}) != json_digest({"a": 2})


# --- content predicates ----------------------------------------------------


def _keyed_iterable(value):
    return bool(value) and all(isinstance(i, tuple) and len(i) == 2 for i in value)


@pytest.fixture
def registry_with_predicate():
    # The shape ecoscope needs: a keyed iterable is a plain `list`, so the type
    # alone cannot distinguish it from any other list.
    keyed = _codec("keyed/v1", (list,), matches=_keyed_iterable)
    return build_registry([*BUILTIN_CODECS, keyed])


def test_predicate_claims_the_shape_it_recognises(registry_with_predicate):
    assert registry_with_predicate.for_value([("a", 1), ("b", 2)]).codec_id == "keyed/v1"


@pytest.mark.parametrize("value", [[1, 2, 3], [], ["a"], [(1, 2, 3)]])
def test_declining_predicate_falls_through_to_the_general_codec(registry_with_predicate, value):
    assert registry_with_predicate.for_value(value).codec_id == "json/v1"


def test_other_types_are_unaffected_by_the_predicate(registry_with_predicate):
    assert registry_with_predicate.for_value({"a": 1}).codec_id == "json/v1"
    assert registry_with_predicate.for_value(b"x").codec_id == "bytes/v1"


def test_predicate_falls_through_across_the_mro():
    # A subclass codec that declines hands the value to a codec claiming a base
    # type, rather than making the value uncacheable.
    class Frame(list):
        pass

    reg = build_registry([*BUILTIN_CODECS, _codec("frame", (Frame,), matches=lambda v: "geo" in v)])
    assert reg.for_value(Frame(["geo"])).codec_id == "frame"
    assert reg.for_value(Frame(["other"])).codec_id == "json/v1"


def test_value_is_uncacheable_when_every_candidate_declines():
    class Frame(list):
        pass

    declines = _codec("frame", (Frame,), matches=lambda v: False)
    assert build_registry([declines]).for_value(Frame()) is None


def test_a_predicate_does_not_excuse_an_ambiguous_claim():
    # Two codecs on one type at one priority stays an error even with
    # predicates: which ran first would otherwise depend on import order.
    with pytest.raises(CodecConflictError, match="both claim"):
        build_registry(
            [
                _codec("a", (str,), matches=lambda v: True),
                _codec("b", (str,), matches=lambda v: False),
            ]
        )


def test_higher_priority_predicate_is_consulted_first():
    order = []

    def make(cid, result, priority):
        def matches(_v):
            order.append(cid)
            return result

        return _codec(cid, (str,), priority=priority, matches=matches)

    reg = build_registry([make("low", True, 0), make("high", False, 10)])
    assert reg.for_value("s").codec_id == "low"
    assert order == ["high", "low"]
