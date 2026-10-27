"""Tests for the tree codec: one encoder, digest and arm rule per step."""

import dataclasses
import enum
import pathlib

import pytest

from wt_task.cache import Codec, Tree, Undigestible
from wt_task.cache._tree import StructureMismatch
from wt_task.skip import SKIP_SENTINEL


class Unit(enum.Enum):
    km = "km"


@dataclasses.dataclass(frozen=True)
class Legend:
    label: str
    source: pathlib.Path
    unit: Unit


@dataclasses.dataclass(frozen=True)
class Caption:
    """Same shape as Legend, a different type: a rename must not decode."""

    label: str
    source: pathlib.Path
    unit: Unit


JSON = {"k": "json"}
DYNAMIC = {"k": "dynamic"}
BYTES = {"k": "ref", "ref": "wt_task.cache:BYTES", "type": None}
PATH = {"k": "ref", "ref": "wt_task.cache:PATH", "type": None}
SKIP = {"k": "ref", "ref": "wt_task.cache:SKIP", "type": None}
UNIT = {"k": "ref", "ref": "wt_task.cache:enum_codec", "type": "test_tree:Unit"}
LEGEND = {
    "k": "dataclass",
    "type": "test_tree:Legend",
    "fields": {"label": JSON, "source": PATH, "unit": UNIT},
}


def tree(structure, **kwargs):
    return Tree(structure, **kwargs)


def roundtrip(structure, value):
    t = tree(structure)
    return t.decode(t.encode(value))


# --- round trips -----------------------------------------------------------


@pytest.mark.parametrize(
    ("structure", "value"),
    [
        (JSON, 7),
        (JSON, None),
        (BYTES, b"\x00raw"),
        (SKIP, SKIP_SENTINEL),
        (LEGEND, Legend("a", pathlib.Path("/var/data/a"), Unit.km)),
        ({"k": "list", "of": BYTES}, [b"a", b"b"]),
        ({"k": "list", "of": LEGEND}, [Legend("a", pathlib.Path("/a"), Unit.km)]),
        ({"k": "tuple", "of": [JSON, BYTES]}, (1, b"x")),
        ({"k": "list", "tuple": True, "of": JSON}, (1, 2, 3)),
        ({"k": "dict", "key": JSON, "of": BYTES}, {"a": b"1", "b": b"2"}),
        ({"k": "union", "of": [BYTES, SKIP]}, SKIP_SENTINEL),
        (DYNAMIC, {"a": [1, None, True, "s"]}),
    ],
)
def test_values_round_trip_through_the_tree(structure, value):
    assert roundtrip(structure, value) == value


def test_a_deeply_mixed_tree_round_trips():
    structure = {
        "k": "list",
        "of": {"k": "tuple", "of": [DYNAMIC, {"k": "union", "of": [LEGEND, SKIP]}]},
    }
    value = [
        (["grouper", "a"], Legend("a", pathlib.Path("/a"), Unit.km)),
        (["grouper", "b"], SKIP_SENTINEL),
    ]
    decoded = roundtrip(structure, value)
    assert decoded[0][1] == value[0][1]
    assert decoded[1][1] is SKIP_SENTINEL


def test_a_dict_can_be_keyed_by_a_tuple_or_by_none():
    structure = {
        "k": "dict",
        "key": {"k": "union", "of": [{"k": "tuple", "of": [JSON, JSON]}, JSON]},
        "of": JSON,
    }
    value = {("region", "north"): 1, None: 2}
    assert roundtrip(structure, value) == value


def test_a_dynamic_key_decodes_back_to_something_hashable():
    # JSON has no tuples, but a dict key has to be hashable either way.
    decoded = roundtrip({"k": "dict", "key": DYNAMIC, "of": JSON}, {("a", "b"): 1})
    assert decoded == {("a", "b"): 1}


# --- tuples through a dynamic node ----------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        ("a", "b"),
        (("event_type", "=", "fire"),),
        [("a", 1), ("b", 2)],
        {"rows": [(1, 2), (3, 4)]},
        ((), (1,)),
        {"a": [(1, {"b": (2,)})]},
    ],
)
def test_tuples_survive_a_dynamic_round_trip(value):
    # A mapvalues key's type comes from `argvalues`, not from any annotation,
    # so `dynamic` is the only node that can carry it — and it has to carry the
    # tuple, or a downstream step keyed by it gets an unhashable list.
    assert roundtrip(DYNAMIC, value) == value


def test_a_dynamic_tuple_and_list_do_not_share_a_digest():
    assert tree(DYNAMIC).digest(("a", "b")) != tree(DYNAMIC).digest(["a", "b"])


@pytest.mark.parametrize(
    "value",
    [{"$t": [1, 2]}, {"$d": {"x": 1}}, {"$t": {"$d": 1}}, {"$t": [1], "other": 2}],
)
def test_a_real_dict_shaped_like_a_tag_is_escaped(value):
    assert roundtrip(DYNAMIC, value) == value


def test_a_payload_in_the_previous_format_reads_as_a_miss():
    # Bumping the payload format must cost a recompute, never a decode that
    # hands back lists where the writer meant tuples.
    stale = b"wt.tree/v1\n" + b'[["a","b"]]' + b"\n"
    with pytest.raises(StructureMismatch, match="this build writes"):
        tree(DYNAMIC).decode(stale)


# --- arm selection ---------------------------------------------------------


def test_the_first_claiming_arm_wins_in_declaration_order():
    first = {"k": "union", "of": [DYNAMIC, SKIP]}
    second = {"k": "union", "of": [SKIP, DYNAMIC]}
    assert tree(first).encode(1) != tree(second).encode(1)
    assert roundtrip(first, 1) == roundtrip(second, 1) == 1


def test_a_dynamic_arm_refuses_a_non_native_value_so_the_next_arm_sees_it():
    assert roundtrip({"k": "union", "of": [DYNAMIC, SKIP]}, SKIP_SENTINEL) is SKIP_SENTINEL


def test_bool_is_not_matched_by_a_codec_claiming_int():
    int_codec = Codec(
        codec_id="int/v1",
        media_type="text/plain",
        types=(int,),
        encode=lambda v: str(v).encode(),
        decode=int,
        digest=lambda v: f"int:{v}",
    )
    structure = {"k": "union", "of": [{"k": "ref", "codec": int_codec}, JSON]}
    assert roundtrip(structure, 3) == 3
    assert roundtrip(structure, True) is True


def test_no_arm_accepts_the_value_so_the_step_declines():
    with pytest.raises(Undigestible, match="no declared union arm"):
        tree({"k": "union", "of": [BYTES, SKIP]}).digest("a string")


@pytest.mark.parametrize(
    ("structure", "value"),
    [
        (JSON, object()),
        (DYNAMIC, object()),
        (BYTES, "not bytes"),
        ({"k": "list", "of": JSON}, 7),
        ({"k": "tuple", "of": [JSON, JSON]}, (1, 2, 3)),
        ({"k": "dict", "key": JSON, "of": JSON}, [1]),
        (LEGEND, object()),
    ],
)
def test_a_value_that_does_not_fit_the_declaration_declines(structure, value):
    with pytest.raises(Undigestible):
        tree(structure).digest(value)


# --- digests ---------------------------------------------------------------


def test_the_digest_is_stable_across_two_encodes():
    value = Legend("a", pathlib.Path("/a"), Unit.km)
    assert tree(LEGEND).digest(value) == tree(LEGEND).digest(value)


def test_the_digest_moves_when_one_leaf_moves():
    base = Legend("a", pathlib.Path("/a"), Unit.km)
    moved = Legend("a", pathlib.Path("/b"), Unit.km)
    assert tree(LEGEND).digest(base) != tree(LEGEND).digest(moved)


def test_the_digest_is_not_the_payload_bytes():
    # Leaf encoders need not be byte-stable; the digest must be anyway.
    t = tree({"k": "list", "of": BYTES})
    assert t.digest([b"a"]) not in repr(t.encode([b"a"]))


# --- stored payloads that no longer match ---------------------------------


def test_a_leaf_codec_id_mismatch_reads_as_a_miss_not_a_wrong_value():
    payload = tree({"k": "list", "of": BYTES}).encode([b"a"])
    with pytest.raises(StructureMismatch, match="bytes/v1"):
        tree({"k": "list", "of": PATH}).decode(payload)


def test_a_dataclass_that_moved_reads_as_a_miss():
    payload = tree(LEGEND).encode(Legend("a", pathlib.Path("/a"), Unit.km))
    renamed = {
        "k": "dataclass",
        "type": "test_tree:Caption",
        "fields": LEGEND["fields"],
    }
    with pytest.raises(StructureMismatch, match="test_tree:Legend"):
        tree(renamed).decode(payload)


def test_a_union_arm_that_no_longer_exists_reads_as_a_miss():
    payload = tree({"k": "union", "of": [JSON, BYTES]}).encode(b"x")
    with pytest.raises(StructureMismatch, match="outside the declaration"):
        tree({"k": "union", "of": [JSON]}).decode(payload)


def test_a_payload_that_is_not_a_tree_is_not_quietly_recomputed():
    with pytest.raises(ValueError, match=r"not a wt\.tree payload"):
        tree(JSON).decode(b"garbage")


# --- a tree as a leaf of another tree -------------------------------------


def test_a_tree_can_be_the_leaf_codec_of_another_tree():
    inner = Tree({"k": "list", "of": BYTES}, types=(list,), codec_id="keyed/v1")
    outer = tree({"k": "union", "of": [{"k": "ref", "codec": inner}, SKIP]})
    assert outer.decode(outer.encode([b"a", b"b"])) == [b"a", b"b"]
    assert outer.decode(outer.encode(SKIP_SENTINEL)) is SKIP_SENTINEL


# --- the digest addresses the payload, so it covers the format ------------


def test_the_wire_format_version_is_part_of_the_content_digest():
    # The header covers the leaf codecs but not how this tree frames them, so
    # without the version a future tree/v3 encoding of the same value would
    # land on the v2 bytes.
    structure = {"k": "list", "of": BYTES}
    assert tree(structure).digest([b"a"]) != Tree(structure, codec_id="tree/v3").digest([b"a"])


def test_the_digest_is_otherwise_stable_for_one_format():
    structure = {"k": "list", "of": BYTES}
    assert tree(structure).digest([b"a"]) == tree(structure).digest([b"a"])
