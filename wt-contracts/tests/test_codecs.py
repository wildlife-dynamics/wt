"""Tests for declared cache codecs: the markers and the return-type walker."""

from __future__ import annotations

import enum
import pathlib
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

import pytest
from pydantic import BaseModel, Field, PrivateAttr, field_serializer, model_serializer
from pydantic_core import Url

from wt_contracts.codecs import (
    Cacheable,
    CodecDeclarationError,
    CodecRef,
    declared_structure,
)
from wt_contracts.registry import RegistryEntry, RegistryMetadata

FRAME = CodecRef("mylib.codecs:FRAME")
Frame = Annotated[list, FRAME]


class ModelCodec(Cacheable):
    __wt_codec__ = "mylib.codecs:model_codec"


class Point(BaseModel, ModelCodec):
    x: int
    y: int


class Unit(enum.Enum):
    km = "km"
    mi = "mi"


def ref(path, type_=None):
    return {"k": "ref", "ref": path, "type": type_}


# --- the markers -----------------------------------------------------------


def test_codec_ref_is_hashable_so_it_can_live_in_annotated():
    assert {CodecRef("a.b:C"), CodecRef("a.b:C")} == {CodecRef("a.b:C")}


def test_cacheable_rejects_a_malformed_ref_at_class_creation():
    with pytest.raises(CodecDeclarationError, match=r"pkg\.mod:NAME"):

        class Bad(Cacheable):
            __wt_codec__ = "not a ref"


def test_cacheable_without_a_declaration_is_inert():
    class Plain(Cacheable):
        pass

    assert declared_structure(Plain) is None


def test_the_mixin_does_not_become_a_pydantic_field():
    assert "__wt_codec__" not in Point.model_fields


# --- rule 1: an explicit CodecRef overrides everything below it ------------


def test_an_annotated_alias_resolves_to_its_ref():
    assert declared_structure(Frame) == ref("mylib.codecs:FRAME")


def test_a_ref_overrides_the_walk_below_it():
    # The underlying `Point` would otherwise resolve to the model codec.
    assert declared_structure(Annotated[Point, CodecRef("mylib.codecs:OTHER")]) == ref(
        "mylib.codecs:OTHER"
    )


def test_a_ref_applies_at_a_nested_level():
    assert declared_structure(dict[str, list[Frame]]) == {
        "k": "dict",
        "key": {"k": "json"},
        "of": {"k": "list", "of": ref("mylib.codecs:FRAME")},
    }


def test_other_annotated_metadata_is_ignored():
    assert declared_structure(Annotated[list, Field(description="hi"), FRAME]) == ref(
        "mylib.codecs:FRAME"
    )


def test_annotated_without_a_ref_walks_through():
    assert declared_structure(Annotated[int, Field(ge=0)]) == {"k": "json"}


# --- rule 2: a class attribute -------------------------------------------


def test_a_cacheable_model_resolves_to_its_class_parameterized_codec():
    assert declared_structure(Point) == ref("mylib.codecs:model_codec", "tests.test_codecs:Point")


def test_a_bare_model_is_not_cacheable():
    class Bare(BaseModel):
        x: int

    assert declared_structure(Bare) is None


@pytest.mark.parametrize(
    ("make", "names"),
    [
        pytest.param(
            lambda: type(
                "WithPrivate",
                (BaseModel, ModelCodec),
                {"__annotations__": {"x": int}, "_hidden": PrivateAttr(default=1)},
            ),
            "_hidden",
            id="private-attr",
        ),
        pytest.param(
            lambda: type(
                "WithExclude",
                (BaseModel, ModelCodec),
                {"__annotations__": {"help_text": str}, "help_text": Field(exclude=True)},
            ),
            "help_text",
            id="excluded-field",
        ),
    ],
)
def test_a_model_that_cannot_round_trip_names_the_field(make, names):
    cls = make()
    with pytest.raises(CodecDeclarationError, match=names):
        declared_structure(cls)


def test_a_model_serializer_is_rejected_by_name():
    class WithModelSerializer(BaseModel, ModelCodec):
        x: int

        @model_serializer
        def _dump(self) -> dict[str, Any]:
            return {"x": self.x}

    with pytest.raises(CodecDeclarationError, match="_dump"):
        declared_structure(WithModelSerializer)


def test_a_field_serializer_is_rejected_by_name():
    class WithFieldSerializer(BaseModel, ModelCodec):
        x: int

        @field_serializer("x")
        def _dump_x(self, v: int) -> str:
            return str(v)

    with pytest.raises(CodecDeclarationError, match="_dump_x"):
        declared_structure(WithFieldSerializer)


def test_a_cacheable_non_model_skips_the_structural_check():
    class Thing(ModelCodec):
        pass

    assert declared_structure(Thing) == ref(
        "mylib.codecs:model_codec",
        "tests.test_codecs:test_a_cacheable_non_model_skips_the_structural_check.<locals>.Thing",
    )


# --- rule 3: builtin leaves ------------------------------------------------


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (bytes, ref("wt_task.cache:BYTES")),
        (pathlib.Path, ref("wt_task.cache:PATH")),
        (pathlib.PurePosixPath, ref("wt_task.cache:PATH")),
        (Url, ref("wt_task.cache:URL")),
        (Unit, ref("wt_task.cache:enum_codec", "tests.test_codecs:Unit")),
    ],
)
def test_builtin_leaves(annotation, expected):
    assert declared_structure(annotation) == expected


def test_the_skip_sentinel_is_recognised_without_importing_wt_task():
    # wt-contracts is upstream of wt-task, so the sentinel is matched by name.
    sentinel = type("SkipSentinel", (), {})
    sentinel.__module__ = "wt_task.skip"
    assert declared_structure(sentinel) == ref("wt_task.cache:SKIP")


# --- rule 4: containers ----------------------------------------------------


def test_list_tuple_dict_and_union():
    assert declared_structure(list[Frame]) == {"k": "list", "of": ref("mylib.codecs:FRAME")}
    assert declared_structure(tuple[int, Frame]) == {
        "k": "tuple",
        "of": [{"k": "json"}, ref("mylib.codecs:FRAME")],
    }
    assert declared_structure(tuple[Frame, ...]) == {
        "k": "list",
        "tuple": True,
        "of": ref("mylib.codecs:FRAME"),
    }
    assert declared_structure(dict[tuple[str, str], Frame]) == {
        "k": "dict",
        "key": {"k": "tuple", "of": [{"k": "json"}, {"k": "json"}]},
        "of": ref("mylib.codecs:FRAME"),
    }


def test_union_preserves_declaration_order():
    assert declared_structure(Frame | None) == {
        "k": "union",
        "of": [ref("mylib.codecs:FRAME"), {"k": "json"}],
    }
    assert declared_structure(None | Frame)["of"][0] == {"k": "json"}


def test_a_union_with_one_poisoning_arm_is_not_cacheable():
    assert declared_structure(Frame | object) is None


def test_a_list_of_something_uncacheable_is_not_cacheable():
    assert declared_structure(list[object]) is None
    assert declared_structure(dict[object, int]) is None


# --- rule 5: dataclasses ---------------------------------------------------


@dataclass
class Legend:
    label: str
    source: pathlib.Path
    unit: Unit


@dataclass
class Derived:
    label: str
    computed: int = field(init=False, default=0)


def test_a_dataclass_resolves_over_its_fields():
    assert declared_structure(Legend) == {
        "k": "dataclass",
        "type": "tests.test_codecs:Legend",
        "fields": {
            "label": {"k": "json"},
            "source": ref("wt_task.cache:PATH"),
            "unit": ref("wt_task.cache:enum_codec", "tests.test_codecs:Unit"),
        },
    }


def test_a_dataclass_with_a_non_init_field_cannot_be_rebuilt():
    assert declared_structure(Derived) is None


def test_a_dataclass_with_an_uncacheable_field_is_not_cacheable():
    @dataclass
    class Holder:
        payload: object

    assert declared_structure(Holder) is None


# --- rule 6 and 7: scalars, and everything else ---------------------------


@pytest.mark.parametrize("annotation", [int, float, str, bool, type(None), Literal["a", "b"]])
def test_scalars_and_literals_are_json(annotation):
    assert declared_structure(annotation) == {"k": "json"}


def test_bool_is_a_scalar_in_its_own_right_not_an_int_subclass_accident():
    # The walker matches by identity, so `bool` never falls through to a codec
    # claiming `int`; the arm-selection rule at run time is what orders the two.
    assert declared_structure(bool) == declared_structure(int) == {"k": "json"}


@pytest.mark.parametrize("annotation", [object, Any, list, dict, tuple, set[int]])
def test_unsupported_annotations_are_not_cacheable(annotation):
    assert declared_structure(annotation) is None


# --- reading the declaration off a function -------------------------------


def returns_a_frame() -> "Frame":  # noqa: UP037  # a string annotation is the point
    """A string annotation, resolved against this module."""
    return []


def returns_nothing():
    return None


def test_a_string_annotation_resolves_against_the_defining_module():
    assert declared_structure(returns_a_frame) == ref("mylib.codecs:FRAME")


def test_a_function_without_a_return_annotation_is_not_cacheable():
    assert declared_structure(returns_nothing) is None


# --- the wire ---------------------------------------------------------------


def test_the_structure_survives_a_registry_wire_round_trip():
    entry = RegistryEntry(
        metadata=RegistryMetadata(title="t", description="d"),
        module_path="m",
        public_module_path="m",
        function_name="f",
        import_statement="from m import f as f",
        json_schema={},
        cache_structure=declared_structure(dict[str, list[Frame]]),
    )
    back = RegistryEntry.model_validate_json(entry.model_dump_json())
    assert back.cache_structure == entry.cache_structure
    assert back.cache_structure_error is None


def test_an_older_registry_payload_validates_unchanged():
    back = RegistryEntry.model_validate(
        {
            "metadata": {},
            "module_path": "m",
            "public_module_path": "m",
            "function_name": "f",
            "import_statement": "from m import f as f",
            "json_schema": {},
        }
    )
    assert back.cache_structure is None


def test_tuple_edge_cases():
    assert declared_structure(tuple[()]) == {"k": "tuple", "of": []}
    assert declared_structure(tuple[int, object]) is None
