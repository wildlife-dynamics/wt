"""What the compiler tells the runtime about one step's cache identity."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

_SKIP = {"k": "ref", "ref": "wt_task.cache:SKIP", "type": None}
_DYNAMIC = {"k": "dynamic"}


@dataclass(frozen=True)
class CacheSpec:
    """Everything needed to key one task instance, split by when it is known.

    The split matters: `static` and `recipe` are hashed at compile time from
    values the compiler can see, while `env`, `params` and the resolved `deps`
    are only knowable at run time.

    Attributes:
        task_instance_id: This step's id in the spec, under which the digest of
            its output is recorded for downstream steps.
        anchor: Importable module the task function lives in.
        function: Task function name.
        recipe: Compile-time hash of (anchor, function, json_schema). Moves when
            the signature changes even if the distribution version does not.
        static: Compile-time hash of the arguments bound to literal values.
        deps: Argument name to the task-instance ids supplying it. A list
            because one argument can collect several upstream outputs, as
            `widgets: [${{ workflow.a.return }}, ${{ workflow.b.return }}]` does.
        env: Argument name to the environment-variable value bound to it.
        params: Runtime parameters for this step, as the DAG passes them.
        servable: Whether a stored result may be served for this step. False for
            a task its author tagged `no-cache`: it then always executes, but
            still digests and promotes its output, so the claim stays about this
            task rather than silently disabling everything below it.
        structure: The return type's declared cache structure, as resolved by
            `wt_contracts.declared_structure`. None means the type declares no
            codec, and the step is not cacheable.
        method: Which execution method this step uses, which decides what the
            declared structure is wrapped in.
        scoped: Whether `WT_CACHE_SCOPE` belongs in this step's key. True only
            for io-tagged tasks: a step that reads the world can see different
            data per principal, while a derived step is a pure function of
            input digests nobody can hold without holding the same content.
    """

    task_instance_id: str
    anchor: str
    function: str
    recipe: str
    static: str = ""
    deps: dict[str, list[str]] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    servable: bool = True
    structure: dict[str, Any] | None = None
    method: Literal["call", "map", "mapvalues"] = "call"
    scoped: bool = False

    @property
    def wrapped_structure(self) -> dict[str, Any] | None:
        """The structure of what this *step* returns, not what the task declares.

        `skipif` can turn any step's return into the sentinel whatever the
        annotation says, and `map`/`mapvalues` wrap it in the container the
        executor builds. The mapvalues key is whatever `argvalues` carried, so
        it is walked at run time rather than declared.

        Examples:
            >>> CacheSpec("s", "pkg", "f", "r", structure={"k": "json"}).wrapped_structure["k"]
            'union'
            >>> CacheSpec("s", "pkg", "f", "r", method="map").wrapped_structure is None
            True
        """
        if self.structure is None:
            return None
        servable = {"k": "union", "of": [self.structure, _SKIP]}
        if self.method == "map":
            return {"k": "list", "of": servable}
        if self.method == "mapvalues":
            return {"k": "list", "of": {"k": "tuple", "of": [_DYNAMIC, servable]}}
        return servable
