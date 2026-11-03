"""One codec for a whole step, driven by the return type's declared structure.

A step's result is a tree — a frame, a list of frames, a dataclass of paths and
enums — and `Tree` is the single codec for all of it: one encoder, one digest
rule, one arm-selection rule. A bare frame is a one-leaf tree, at a cost of
some tens of bytes of header.

The payload is a JSON header mirroring the *value* (scalars inline, leaves
replaced by `{c, o, n}` references) followed by the leaf blobs. The digest is
taken over the same header with each leaf's own `digest` in place of its
offsets, never over the bytes: encoders like parquet are not byte-stable, and
an unstable digest silently invalidates everything downstream on every run.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import re
import warnings
from typing import TYPE_CHECKING, Any

from ._codec import Codec, Undigestible
from ._settings import active_settings

if TYPE_CHECKING:
    from collections.abc import Callable

    Leaf = Callable[["Codec | Tree", Any], Any]

MAGIC_PREFIX = b"wt.tree/"
# Bump on any change to the payload layout: a payload in another format must
# miss rather than decode, e.g. into lists where the writer meant tuples.
MAGIC = MAGIC_PREFIX + b"v1\n"
TREE_CODEC_ID = "tree/v1"
TREE_MEDIA_TYPE = "application/vnd.wt.tree"

# One-key dicts tag what JSON cannot express. `$d` escapes a real dict that
# would otherwise read as a tag; escaping is one level deep, never nested.
_TUPLE_TAG = "$t"
_DICT_TAG = "$d"

_NATIVE_SCALARS = (bool, int, float, str)

# A codec id becomes nested directories under `content/`, so each segment must
# be a plain, portable name: no `..`, no separators, nothing a filesystem or an
# object store would read specially.
_PATH_SEGMENT = re.compile(r"[A-Za-z0-9_.-]+")


class StructureMismatch(Exception):  # noqa: N818  # a miss signal, not an error the caller sees
    """Raised when a stored payload no longer matches the declared structure.

    A leaf written by a different codec version, a union arm that no longer
    exists, a dataclass that moved. Read as a miss rather than corruption: the
    entry is intact, it just describes a value this code would not produce.
    """


@dataclasses.dataclass(frozen=True)
class _Leaf:
    codec: Codec | Tree


@dataclasses.dataclass(frozen=True)
class _Scalar:
    pass


@dataclasses.dataclass(frozen=True)
class _Dynamic:
    pass


@dataclasses.dataclass(frozen=True)
class _Seq:
    of: Node
    as_tuple: bool


@dataclasses.dataclass(frozen=True)
class _Fixed:
    of: tuple[Node, ...]


@dataclasses.dataclass(frozen=True)
class _Mapping:
    key: Node
    of: Node


@dataclasses.dataclass(frozen=True)
class _Union:
    of: tuple[Node, ...]


@dataclasses.dataclass(frozen=True)
class _Dataclass:
    cls: type
    type_ref: str
    fields: tuple[tuple[str, Node], ...]


Node = _Leaf | _Scalar | _Dynamic | _Seq | _Fixed | _Mapping | _Union | _Dataclass


def _import_ref(ref: str) -> Any:  # noqa: ANN401  # a codec, or a callable building one
    """Import `"pkg.mod:NAME"`, raising ImportError for either half failing."""
    module_name, _, attribute = ref.partition(":")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attribute)
    except AttributeError as e:
        raise ImportError(f"{module_name!r} has no attribute {attribute!r}") from e


def _compile(structure: dict[str, Any]) -> Node:
    """Turn one declared node into its resolved form, importing any refs."""
    kind = structure["k"]
    if kind == "json":
        return _Scalar()
    if kind == "dynamic":
        return _Dynamic()
    if kind == "ref":
        # A structure built in Python may name the codec object directly; the
        # wire form always names it by import path.
        codec = structure.get("codec")
        if codec is None:
            factory = _import_ref(structure["ref"])
            type_ref = structure.get("type")
            codec = factory if type_ref is None else factory(_import_ref(type_ref))
        return _Leaf(codec)
    if kind == "list":
        return _Seq(_compile(structure["of"]), as_tuple=bool(structure.get("tuple")))
    if kind == "tuple":
        return _Fixed(tuple(_compile(s) for s in structure["of"]))
    if kind == "dict":
        return _Mapping(_compile(structure["key"]), _compile(structure["of"]))
    if kind == "union":
        return _Union(tuple(_compile(s) for s in structure["of"]))
    if kind == "dataclass":
        cls = _import_ref(structure["type"])
        return _Dataclass(
            cls=cls,
            type_ref=structure["type"],
            fields=tuple((name, _compile(s)) for name, s in structure["fields"].items()),
        )
    raise ValueError(f"Unknown cache structure node {kind!r}")


def _claims(node: Node, value: Any) -> bool:  # noqa: ANN401  # inspects any runtime value
    """Whether `node` is the union arm `value` belongs to. Shallow by design."""
    match node:
        case _Leaf(codec):
            if not codec.types:
                return False
            if not codec.accepts_subclasses:
                return type(value) is codec.types[0]
            # `bool` is an `int` subclass, so a codec claiming `int` would
            # otherwise swallow True/False on its way past a `json` arm.
            if isinstance(value, bool) and bool not in codec.types:
                return False
            return isinstance(value, codec.types)
        case _Scalar():
            return value is None or isinstance(value, _NATIVE_SCALARS)
        case _Dynamic():
            return _is_native(value)
        case _Seq(_, as_tuple):
            return isinstance(value, tuple if as_tuple else list)
        case _Fixed(of):
            return isinstance(value, tuple) and len(value) == len(of)
        case _Mapping():
            return isinstance(value, dict)
        case _Union(of):
            return any(_claims(arm, value) for arm in of)
        case _Dataclass(cls, _, _):
            return type(value) is cls
    return False


def _is_native(value: Any) -> bool:  # noqa: ANN401  # inspects any runtime value
    """Whether JSON can hold `value` without a converter losing information."""
    if value is None or isinstance(value, _NATIVE_SCALARS):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_native(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_native(v) for k, v in value.items())
    return False


def _tagged(value: Any) -> Any:  # noqa: ANN401  # walks any JSON-native value
    """Render a JSON-native value, keeping tuples distinguishable from lists.

    A `dynamic` node carries values whose type no annotation pinned — above all
    a mapvalues key, which is whatever `argvalues` held. Those are tuples in
    practice, and a hit that handed back a list would be unhashable the moment
    a downstream step grouped by it, so the tuple has to survive the round trip
    and has to digest differently from the list.
    """
    if isinstance(value, tuple):
        return {_TUPLE_TAG: [_tagged(v) for v in value]}
    if isinstance(value, list):
        return [_tagged(v) for v in value]
    if isinstance(value, dict):
        tagged = {k: _tagged(v) for k, v in value.items()}
        return {_DICT_TAG: tagged} if _is_tag(tagged) else tagged
    return value


def _is_tag(value: Any) -> bool:  # noqa: ANN401  # inspects a decoded header node
    return (
        isinstance(value, dict)
        and len(value) == 1
        and next(iter(value))
        in (
            _TUPLE_TAG,
            _DICT_TAG,
        )
    )


def _untagged(value: Any) -> Any:  # noqa: ANN401  # rebuilds any JSON-native value
    """Invert `_tagged`."""
    if isinstance(value, list):
        return [_untagged(v) for v in value]
    if not isinstance(value, dict):
        return value
    if _is_tag(value):
        inner = next(iter(value.values()))
        if _TUPLE_TAG in value:
            return tuple(_untagged(v) for v in inner)
        # An escaped dict: its one level of tagging is spent, so decode its
        # members plainly rather than re-reading the escape.
        return {k: _untagged(v) for k, v in inner.items()}
    return {k: _untagged(v) for k, v in value.items()}


def _encode(node: Node, value: Any, leaf: Leaf) -> Any:  # noqa: ANN401  # walks any task return
    """Build the header for `value`, handing each leaf to `leaf(codec, value)`.

    Raises:
        Undigestible: If the value does not fit the declared structure. That is
            a refusal to cache, not an error: the step has already run.
    """
    match node:
        case _Leaf(codec):
            # Refusing subclasses has to bite here too, not only between union arms: a
            # class-parameterized codec handed a subclass would narrow it away.
            if codec.types and not _claims(node, value):
                raise Undigestible(f"{codec.codec_id} does not accept {type(value).__name__}")
            return leaf(codec, value)
        case _Scalar():
            if value is not None and not isinstance(value, _NATIVE_SCALARS):
                raise Undigestible(f"expected a JSON scalar, got {type(value).__name__}")
            return value
        case _Dynamic():
            if not _is_native(value):
                raise Undigestible(f"{type(value).__name__} is not JSON-native")
            return _tagged(value)
        case _Seq(of, _):
            if not isinstance(value, (list, tuple)):
                raise Undigestible(f"expected a sequence, got {type(value).__name__}")
            return [_encode(of, v, leaf) for v in value]
        case _Fixed(of):
            if not isinstance(value, (list, tuple)) or len(value) != len(of):
                raise Undigestible(f"expected {len(of)} elements, got {value!r}")
            return [_encode(n, v, leaf) for n, v in zip(of, value, strict=True)]
        case _Mapping(key, of):
            if not isinstance(value, dict):
                raise Undigestible(f"expected a mapping, got {type(value).__name__}")
            return [[_encode(key, k, leaf), _encode(of, v, leaf)] for k, v in value.items()]
        case _Union(of):
            for index, arm in enumerate(of):
                if _claims(arm, value):
                    return {"u": index, "v": _encode(arm, value, leaf)}
            raise Undigestible(f"no declared union arm accepts {type(value).__name__}")
        case _Dataclass(cls, type_ref, fields):
            if type(value) is not cls:
                raise Undigestible(f"expected {type_ref}, got {type(value).__name__}")
            return {
                "t": type_ref,
                "f": {name: _encode(n, getattr(value, name), leaf) for name, n in fields},
            }
    raise Undigestible(f"unhandled structure node {node!r}")


def _decode(node: Node, header: Any, payload: bytes) -> Any:  # noqa: ANN401  # rebuilds any task return
    """Rebuild the value `header` describes, reading leaf blobs from `payload`.

    Raises:
        StructureMismatch: If the stored value no longer matches the declaration.
    """
    match node:
        case _Leaf(codec):
            if not isinstance(header, dict) or header.get("c") != codec.codec_id:
                raise StructureMismatch(
                    f"leaf was written by {header.get('c') if isinstance(header, dict) else header!r}, "
                    f"the declaration now resolves {codec.codec_id!r}"
                )
            offset, length = header["o"], header["n"]
            return codec.decode(payload[offset : offset + length])
        case _Scalar():
            return header
        case _Dynamic():
            return _untagged(header)
        case _Seq(of, as_tuple):
            decoded = [_decode(of, h, payload) for h in header]
            return tuple(decoded) if as_tuple else decoded
        case _Fixed(of):
            if len(header) != len(of):
                raise StructureMismatch(f"expected {len(of)} elements, stored {len(header)}")
            return tuple(_decode(n, h, payload) for n, h in zip(of, header, strict=True))
        case _Mapping(key, of):
            return {_hashable(_decode(key, k, payload)): _decode(of, v, payload) for k, v in header}
        case _Union(of):
            index = header["u"]
            if not 0 <= index < len(of):
                raise StructureMismatch(f"stored union arm {index} is outside the declaration")
            return _decode(of[index], header["v"], payload)
        case _Dataclass(cls, type_ref, fields):
            if header.get("t") != type_ref:
                raise StructureMismatch(
                    f"stored {header.get('t')!r}, declaration says {type_ref!r}"
                )
            return cls(**{name: _decode(n, header["f"][name], payload) for name, n in fields})
    raise StructureMismatch(f"unhandled structure node {node!r}")


def _hashable(key: Any) -> Any:  # noqa: ANN401  # any decoded dict key
    """Make a decoded key usable as one. JSON has no tuples, dict keys need one."""
    return tuple(key) if isinstance(key, list) else key


class Tree:
    """The codec for one step's whole result.

    Duck-type compatible with `Codec`, so a tree can itself be a leaf of
    another tree — which is how a task library declares a codec for a
    container type it owns.

    Args:
        structure: The declared structure. A `ref` node may carry a resolved
            `codec` instead of an import path, for a tree built in Python.
        types: Runtime types this tree accepts, when used as a union arm.
        accepts_subclasses: As on `Codec`.
        codec_id: Recorded in the header of any tree embedding this one.
        media_type: Media type of the encoded payload.

    Raises:
        ImportError: If a `ref` or a dataclass type cannot be imported.
        ValueError: If the structure contains an unknown node kind.

    Examples:
        >>> tree = Tree({"k": "list", "of": {"k": "json"}})
        >>> tree.decode(tree.encode([1, "two", None]))
        [1, 'two', None]
        >>> tree.digest([1, 2]) == tree.digest([1, 2])
        True
    """

    def __init__(
        self,
        structure: dict[str, Any],
        *,
        types: tuple[type, ...] = (),
        accepts_subclasses: bool = True,
        codec_id: str = TREE_CODEC_ID,
        media_type: str = TREE_MEDIA_TYPE,
    ) -> None:
        self.root = _compile(structure)
        self.types = types
        self.accepts_subclasses = accepts_subclasses
        self.codec_id = codec_id
        self.media_type = media_type

    def encode(self, value: Any) -> bytes:  # noqa: ANN401  # encodes any task return
        """Encode `value` as a header plus the concatenated leaf blobs."""
        blobs: list[bytes] = []
        offset = 0

        def leaf(codec: Codec | Tree, v: Any) -> dict[str, Any]:  # noqa: ANN401  # encodes any leaf value
            nonlocal offset
            blob = codec.encode(v)
            entry = {"c": codec.codec_id, "o": offset, "n": len(blob)}
            blobs.append(blob)
            offset += len(blob)
            return entry

        header = _encode(self.root, value, leaf)
        return MAGIC + _canonical(header) + b"\n" + b"".join(blobs)

    def decode(self, data: bytes) -> Any:  # noqa: ANN401  # rebuilds any task return
        """Decode a payload this tree wrote.

        Raises:
            StructureMismatch: If the payload no longer matches the declaration, or
                was written in an older payload format.
            ValueError: If the payload is not a tree payload at all.
        """
        if not data.startswith(MAGIC):
            if data.startswith(MAGIC_PREFIX):
                # A format this build no longer reads. Stale, not corrupt.
                raise StructureMismatch(
                    f"payload is {data[: len(MAGIC)]!r}, this build writes {MAGIC!r}"
                )
            raise ValueError("not a wt.tree payload")
        body = data[len(MAGIC) :]
        header_bytes, _, payload = body.partition(b"\n")
        return _decode(self.root, json.loads(header_bytes), payload)

    def digest(self, value: Any) -> str:  # noqa: ANN401  # digests any task return
        """Return a stable sha256 over the value's shape and its leaves' digests.

        The wire-format version is folded in because the digest addresses the
        payload directly: the header covers the leaf codecs but not how this
        tree frames them, so without it a future `tree/v2` encoding of the same
        value would land on the v1 bytes. It also keeps a format bump moving
        every downstream key, since this is what `record` promotes.

        Raises:
            Undigestible: If the value does not fit the declared structure, or
                a leaf codec declines it.
        """
        header = _encode(
            self.root, value, lambda codec, v: {"c": codec.codec_id, "d": codec.digest(v)}
        )
        return hashlib.sha256(_canonical({"v": self.codec_id, "h": header})).hexdigest()


def _canonical(header: Any) -> bytes:  # noqa: ANN401  # the header is JSON by construction
    return json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")


def strict() -> bool:
    """Whether a codec that will not resolve should fail the run.

    On in tests and CI, off on a deployed service: there, the environment that
    compiled a spec and the one running it can skew, and losing the cache is
    always preferable to losing the run.
    """
    return active_settings().strict


def resolve_structure(structure: dict[str, Any] | None) -> Tree | None:
    """Resolve a declared structure into the tree codec for one step.

    Args:
        structure: The structure the compiler emitted, or None for a step whose
            return type declares no codec.

    Returns:
        The tree, or None when the step cannot be cached.

    Raises:
        ImportError: If a ref will not import and `strict` is set.

    Examples:
        >>> resolve_structure(None) is None
        True
        >>> resolve_structure({"k": "json"}).codec_id
        'tree/v1'
    """
    if structure is None:
        return None
    try:
        return Tree(structure)
    except (ImportError, AttributeError, KeyError, TypeError, ValueError) as e:
        if strict():
            raise
        warnings.warn(
            f"Cache structure {structure!r} could not be resolved ({e!r}); "
            f"this step will not be cached.",
            stacklevel=2,
        )
        return None


def is_safe_codec_dir(codec_id: str) -> bool:
    """Whether `codec_id` can name a directory under `content/` as it stands.

    Examples:
        >>> is_safe_codec_dir("ecoscope.frame/v1")
        True
        >>> is_safe_codec_dir("../escape") or is_safe_codec_dir("/abs") or is_safe_codec_dir("a//b")
        False
    """
    return all(
        _PATH_SEGMENT.fullmatch(segment) and segment not in (".", "..")
        for segment in codec_id.split("/")
    )


def content_dir(structure: dict[str, Any], tree: Tree) -> str:
    """Where a step's payloads are filed: its root codec's id.

    A step declaring one leaf — a `CodecRef` alias, a `Cacheable` class, a
    builtin like PATH — is filed under that leaf codec, so a store's frames sit
    together; anything structural is filed under the tree's own id. An id that
    is not a safe relative path falls back to the tree's.

    Args:
        structure: The task's declared structure, before `skipif` or a map
            method wraps it.
        tree: The step's resolved tree, whose id is the fallback.

    Examples:
        >>> content_dir({"k": "ref", "ref": "wt_task.cache:PATH"}, Tree({"k": "json"}))
        'path/v1'
        >>> content_dir({"k": "list", "of": {"k": "json"}}, Tree({"k": "json"}))
        'tree/v1'
    """
    if structure.get("k") == "ref":
        node = _compile(structure)
        if isinstance(node, _Leaf) and is_safe_codec_dir(node.codec.codec_id):
            return node.codec.codec_id
    return tree.codec_id
