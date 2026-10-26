"""Declaring how a task's return value is cached, from its return type.

A task library says what a value *is* — by annotating a type alias with
:class:`CodecRef`, or by mixing :class:`Cacheable` into a class — and
:func:`declared_structure` turns the return annotation into a JSON-serializable
tree that wt-registry ships and wt-task resolves into codecs. Nothing here
imports a codec: refs are strings, so the resolver lives in wt-task and this
module stays pure typing.

Anything the rules below do not recognise resolves to ``None``: not cacheable.
That is deliberate — this walker is a third type interpreter beside pydantic
and pandera, and a wrong guess silently mis-encodes a result.
"""

from __future__ import annotations

import builtins
import dataclasses
import enum
import inspect
import pathlib
import re
import types
import typing
from typing import Any, ClassVar, get_args, get_origin, get_type_hints

import pydantic_core
from pydantic import BaseModel

Structure = dict[str, Any]
"""A node of the declared cache structure. JSON-serializable, by construction."""

_REF_PATTERN = re.compile(r"[\w.]+:\w+")

# Refs into wt-task's builtin leaf codecs. Named rather than imported: wt-contracts
# is upstream of wt-task, and the resolver is the only thing that needs the objects.
_SKIP_REF = "wt_task.cache:SKIP"
_BYTES_REF = "wt_task.cache:BYTES"
_PATH_REF = "wt_task.cache:PATH"
_URL_REF = "wt_task.cache:URL"
_ENUM_REF = "wt_task.cache:enum_codec"

_SCALAR_TYPES = (bool, int, float, str, type(None))


class CodecDeclarationError(ValueError):
    """Raised when a class declares a codec it cannot honour."""


@dataclasses.dataclass(frozen=True)
class CodecRef:
    """Declares the codec for a type: ``Annotated[T, CodecRef("pkg.mod:NAME")]``.

    ``NAME`` is either a ``Codec`` or, for a class-parameterized codec, a
    callable ``(type) -> Codec``.

    Attributes:
        ref: Import path of the codec, as ``"pkg.mod:NAME"``.

    Examples:
        >>> CodecRef("ecoscope.platform.codecs:FRAME").ref
        'ecoscope.platform.codecs:FRAME'
    """

    ref: str


class Cacheable:
    """Mixin declaring the codec for instances of a class.

    A mixin rather than a base class so one mechanism covers pydantic models,
    dataclasses and enums, and composes with whatever base a class already has.
    The dunder name keeps it out of pydantic's field collection.

    Attributes:
        __wt_codec__: Import path of a callable ``(type) -> Codec``, as
            ``"pkg.mod:NAME"``.

    Examples:
        >>> class ModelCodec(Cacheable):
        ...     __wt_codec__ = "mylib.codecs:model_codec"
        >>> class Thing(ModelCodec):
        ...     pass
        >>> Thing.__wt_codec__
        'mylib.codecs:model_codec'
    """

    __wt_codec__: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:  # noqa: ANN401  # forwards whatever the real base takes
        """Check the ref's format. Importing it is the resolver's job, at run time."""
        super().__init_subclass__(**kwargs)
        ref = getattr(cls, "__wt_codec__", None)
        if ref is not None and not _REF_PATTERN.fullmatch(ref):
            raise CodecDeclarationError(
                f"{cls.__qualname__}.__wt_codec__ must be 'pkg.mod:NAME', got {ref!r}"
            )


class ModelDumpCacheable(Cacheable):
    """Mixin for a pydantic model whose codec goes through ``model_dump``/``model_validate``.

    Declaring through this mixin is what subjects the model to the round-trip
    check: private attributes, serializers and excluded fields are all lost on
    the way through that codec. A codec that encodes the model some other way
    declares through plain :class:`Cacheable` and is not checked.

    Examples:
        >>> class ModelCodec(ModelDumpCacheable):
        ...     __wt_codec__ = "mylib.codecs:model_codec"
        >>> issubclass(ModelCodec, Cacheable)
        True
    """


def declared_structure(target: Any) -> Structure | None:  # noqa: ANN401  # a function or a type annotation
    """Resolve a task's declared cache structure, or None if it has no codec.

    Args:
        target: A task function, whose return annotation is read (string
            annotations resolve against its defining module), or a type
            annotation directly.

    Returns:
        A JSON-serializable structure tree, or None when the type declares no
        codec anywhere it needs one.

    Raises:
        CodecDeclarationError: If a class declares a codec it cannot honour.

    Examples:
        >>> def count() -> int: ...
        >>> declared_structure(count)
        {'k': 'json'}
        >>> declared_structure(list[bytes])
        {'k': 'list', 'of': {'k': 'ref', 'ref': 'wt_task.cache:BYTES', 'type': None}}
        >>> declared_structure(object) is None
        True
    """
    if inspect.isroutine(target):
        hints = get_type_hints(target, include_extras=True)
        if "return" not in hints:
            return None
        target = hints["return"]
    return _structure(target)


def _structure(annotation: Any) -> Structure | None:  # noqa: ANN401  # walks arbitrary annotations
    """Resolve one annotation node, applying the rules in declaration order."""
    if hasattr(annotation, "__metadata__"):
        for meta in annotation.__metadata__:
            if isinstance(meta, CodecRef):
                return {"k": "ref", "ref": meta.ref, "type": None}
        return _structure(get_args(annotation)[0])

    if isinstance(annotation, type):
        declared = _declared_class_ref(annotation)
        if declared is not None:
            return declared

    args = get_args(annotation)
    # Dotted names throughout: a bare name in a `case` is a capture pattern, not
    # a comparison, so `case list:` would match anything.
    match get_origin(annotation):
        case typing.Literal:
            return {"k": "json"}
        case typing.Union | types.UnionType:
            return _union([_structure(arg) for arg in args])
        case builtins.list:
            return _container({"k": "list"}, "of", _structure(args[0]))
        case builtins.tuple:
            return _tuple(args)
        case builtins.dict:
            key, value = (_structure(arg) for arg in args)
            if key is None or value is None:
                return None
            return {"k": "dict", "key": key, "of": value}

    if dataclasses.is_dataclass(annotation) and isinstance(annotation, type):
        return _dataclass(annotation)

    if annotation in _SCALAR_TYPES:
        return {"k": "json"}

    return None


def _declared_class_ref(cls: type) -> Structure | None:
    """Resolve rules 2 and 3: a declared codec, or a builtin leaf, for `cls`."""
    ref = getattr(cls, "__wt_codec__", None)
    if ref is not None:
        if issubclass(cls, ModelDumpCacheable) and issubclass(cls, BaseModel):
            _check_model_round_trips(cls)
        return _ref(ref, cls)

    if cls.__module__ == "wt_task.skip" and cls.__name__ == "SkipSentinel":
        return _ref(_SKIP_REF, None)
    if cls is bytes:
        return _ref(_BYTES_REF, None)
    if issubclass(cls, pathlib.PurePath):
        return _ref(_PATH_REF, None)
    if issubclass(cls, pydantic_core.Url):
        return _ref(_URL_REF, None)
    if issubclass(cls, enum.Enum):
        return _ref(_ENUM_REF, cls)
    return None


def _ref(ref: str, cls: type | None) -> Structure:
    return {"k": "ref", "ref": ref, "type": None if cls is None else type_ref(cls)}


def type_ref(cls: type) -> str:
    """Return the import path of a class, as ``"module:qualname"``.

    Examples:
        >>> type_ref(CodecRef)
        'wt_contracts.codecs:CodecRef'
    """
    return f"{cls.__module__}:{cls.__qualname__}"


def _container(node: Structure, key: str, child: Structure | None) -> Structure | None:
    if child is None:
        return None
    return {**node, key: child}


def _union(arms: list[Structure | None]) -> Structure | None:
    if any(arm is None for arm in arms):
        return None
    return {"k": "union", "of": arms}


def _tuple(args: tuple[Any, ...]) -> Structure | None:
    if len(args) == 2 and args[1] is Ellipsis:
        return _container({"k": "list", "tuple": True}, "of", _structure(args[0]))
    if args == ((),):  # tuple[()] — the empty tuple
        return {"k": "tuple", "of": []}
    members = [_structure(arg) for arg in args]
    if any(member is None for member in members):
        return None
    return {"k": "tuple", "of": members}


def _dataclass(cls: type) -> Structure | None:
    """Resolve a dataclass over its fields, or None if it cannot be rebuilt.

    An ``init=False`` field is not reconstructible from ``cls(**fields)``, so
    the whole dataclass declines rather than decoding into a wrong instance.
    """
    hints = get_type_hints(cls, include_extras=True)
    fields: dict[str, Structure] = {}
    for field in dataclasses.fields(cls):
        if not field.init:
            return None
        resolved = _structure(hints.get(field.name, field.type))
        if resolved is None:
            return None
        fields[field.name] = resolved
    return {"k": "dataclass", "type": type_ref(cls), "fields": fields}


def _check_model_round_trips(cls: type[BaseModel]) -> None:
    """Reject a declared model whose dump cannot be validated back into itself.

    The structural half of the check — the half that needs no instance — run
    once here instead of on every value the cache sees. Only for models
    declared through :class:`ModelDumpCacheable`.

    Raises:
        CodecDeclarationError: Naming the attribute or field that breaks it.
    """
    if cls.__private_attributes__:
        names = ", ".join(sorted(cls.__private_attributes__))
        raise CodecDeclarationError(
            f"{type_ref(cls)} declares a codec but has private attributes ({names}), "
            f"which a model_dump/model_validate round trip drops."
        )
    decorators = cls.__pydantic_decorators__
    if decorators.model_serializers:
        raise CodecDeclarationError(
            f"{type_ref(cls)} declares a codec but has a model_serializer "
            f"({', '.join(sorted(decorators.model_serializers))}), whose output "
            f"model_validate cannot be relied on to accept."
        )
    if decorators.field_serializers:
        raise CodecDeclarationError(
            f"{type_ref(cls)} declares a codec but has a field_serializer "
            f"({', '.join(sorted(decorators.field_serializers))}), whose output "
            f"model_validate cannot be relied on to accept."
        )
    excluded = sorted(name for name, f in cls.model_fields.items() if f.exclude)
    if excluded:
        raise CodecDeclarationError(
            f"{type_ref(cls)} declares a codec but excludes field(s) "
            f"{', '.join(excluded)} from its dump, which a round trip cannot restore."
        )


__all__ = [
    "Cacheable",
    "CodecDeclarationError",
    "CodecRef",
    "ModelDumpCacheable",
    "Structure",
    "declared_structure",
    "type_ref",
]
