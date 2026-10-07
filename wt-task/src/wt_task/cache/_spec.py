"""What the compiler tells the runtime about one step's cache identity."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CacheSpec:
    """Everything needed to key one task instance, split by when it is known.

    The split matters: `static` and `recipe` are hashed at compile time from
    values the compiler can see, while `env`, `params` and the resolved `deps`
    are only knowable at run time.

    Attributes:
        task_instance_id: This step's id in the spec, under which its identity is
            recorded for downstream steps.
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
        source: Whether this step reads the outside world. A source contributes
            the digest of its *output* to downstream keys rather than its own
            identity, so that re-reading unchanged data still cuts off
            recomputation below it, and re-reading changed data does not.
    """

    task_instance_id: str
    anchor: str
    function: str
    recipe: str
    static: str = ""
    deps: dict[str, list[str]] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    source: bool = False
