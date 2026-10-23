"""The two halves of a step's cache identity.

`CacheSpec` is what the compiler knows and the runtime cannot work out —
hashes of the spec's own text. `ResolvedTask` is the other half, worked out
from the wrapped function when `.cached()` runs.
"""

from __future__ import annotations

import functools
import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from wt_contracts import CodecDeclarationError, declared_structure

from ._tree import content_dir, resolve_structure, strict

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ._key import Outcome
    from ._tree import Tree

METHODS = ("call", "map", "mapvalues")

_SKIP = {"k": "ref", "ref": "wt_task.cache:SKIP", "type": None}
_DYNAMIC = {"k": "dynamic"}


@dataclass(frozen=True)
class CacheSpec:
    """What the compiler tells the runtime about one step's cache identity.

    Only what the spec's text decides. The task's own identity, the structure
    of its return and the parameters it was given all come from elsewhere at
    run time, so none of them is emitted into the DAG.

    Attributes:
        signature: Hash of the task's module, function name and JSON schema.
            Moves when the signature changes even if the distribution version
            does not.
        fixed_inputs: Hash of the literal argument values, of where each
            upstream reference sits, and of the map/mapvalues argnames.
        upstream_inputs: Argument name to the task-instance ids supplying it,
            whose output digests are looked up at run time. A list because one
            argument can collect several upstream outputs, as
            `widgets: [${{ workflow.a.return }}, ${{ workflow.b.return }}]` does.
        env: Names of the environment variables bound to arguments. Their
            values are read when the key is built: a per-run results directory
            must move the key, or a warm run would replay a URL into a
            directory that no longer exists.
        servable: Whether a stored result may be served for this step. False
            for a task its author tagged `no-cache`: it then always executes,
            but still digests and promotes its output, so the claim stays about
            this task rather than silently disabling everything below it.
        scoped: Whether `WT_CACHE__SCOPE` belongs in this step's key. True only
            for io-tagged tasks: a step that reads the world can see different
            data per principal, while a derived step is a pure function of
            input digests nobody can hold without holding the same content.
    """

    signature: str
    fixed_inputs: str = ""
    upstream_inputs: dict[str, list[str]] = field(default_factory=dict)
    env: list[str] = field(default_factory=list)
    servable: bool = True
    scoped: bool = False


@dataclass(frozen=True)
class ResolvedTask:
    """What `.cached()` works out from the wrapped function, once.

    Resolved when the builder runs rather than per call, because `.partial()`
    later replaces `func` with a `functools.partial` — which carries neither
    `__module__` nor `__name__` — and because the codec imports should not
    repeat on every call.

    Attributes:
        anchor: Module the task function is defined in. Only its top-level
            package is read, to find the distribution version, so a private
            submodule is as good as the registry's public path.
        function: Task function name.
        trees: Tree codec per execution method; None where the step cannot be
            cached.
        outcome: When there is no tree, which run-report outcome says so.
        reason: The same, in words.
        root_codec: Directory under `content/` for the `call` method's
            payloads. The map methods always wrap the value in a list, so they
            file under their tree's id.
    """

    anchor: str
    function: str
    trees: Mapping[str, Tree | None]
    outcome: Outcome | None = None
    reason: str | None = None
    root_codec: str | None = None

    def tree(self, method: str) -> Tree | None:
        """Return the codec for the method being executed, if there is one."""
        return self.trees.get(method)

    def content_dir(self, method: str, tree: Tree) -> str:
        """Return the directory under `content/` this method's payloads go in."""
        if method == "call" and self.root_codec is not None:
            return self.root_codec
        return tree.codec_id


def _wrapped(structure: dict[str, Any] | None, method: str) -> dict[str, Any] | None:
    """The structure of what the *step* returns, not what the task declares.

    `skipif` can turn any step's return into the sentinel whatever the
    annotation says, and `map`/`mapvalues` wrap it in the container the
    executor builds. The mapvalues key is whatever `argvalues` carried, so it
    is walked at run time rather than declared.
    """
    if structure is None:
        return None
    servable = {"k": "union", "of": [structure, _SKIP]}
    if method == "map":
        return {"k": "list", "of": servable}
    if method == "mapvalues":
        return {"k": "list", "of": {"k": "tuple", "of": [_DYNAMIC, servable]}}
    return servable


@functools.cache
def _declared(func: Callable[..., Any]) -> dict[str, Any] | None:
    """Memoised `declared_structure`: one walk per task function per process."""
    return declared_structure(func)


def resolve_task(func: Callable[..., Any]) -> ResolvedTask:
    """Work out where `func` lives and how each of its methods' results encode.

    A return type that declares no codec, a declaration the type cannot honour,
    or a codec ref that will not import all leave the step uncacheable rather
    than failing the run — unless `WT_CACHE__STRICT` is set, which is how tests
    and CI see them.

    Args:
        func: The unwrapped task function.

    Returns:
        The resolved half of this step's cache identity.

    Examples:
        >>> def add(a: int, b: int) -> int:
        ...     return a + b
        >>> resolved = resolve_task(add)
        >>> resolved.function
        'add'
        >>> resolved.tree("call").codec_id
        'tree/v2'
        >>> resolved.root_codec
        'tree/v2'
    """
    anchor = getattr(func, "__module__", "") or ""
    function = getattr(func, "__name__", "") or ""
    try:
        structure = _declared(func)
    except CodecDeclarationError as e:
        if strict():
            raise
        warnings.warn(
            f"{anchor}.{function} declares a codec it cannot honour ({e}); "
            f"this step will not be cached.",
            stacklevel=2,
        )
        return ResolvedTask(anchor, function, {}, "refused", str(e))

    if structure is None:
        return ResolvedTask(anchor, function, {}, "uncacheable", "return type declares no codec")

    trees = {method: resolve_structure(_wrapped(structure, method)) for method in METHODS}
    if any(tree is None for tree in trees.values()):
        # `resolve_structure` has already warned, naming the ref.
        return ResolvedTask(
            anchor, function, {}, "refused", "declared codec refs could not be imported"
        )
    root_codec = content_dir(structure, cast("Tree", trees["call"]))
    return ResolvedTask(anchor, function, trees, root_codec=root_codec)
