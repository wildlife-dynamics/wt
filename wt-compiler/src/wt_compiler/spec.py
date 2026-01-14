"""Workflow specification models for the compiler.

This module defines the Spec and TaskInstance models that represent
the workflow specification (spec.yaml) input format.
"""

import builtins
import hashlib
import keyword
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    Discriminator,
    Field,
    PlainSerializer,
    computed_field,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic import Tag as PydanticTag
from pydantic.functional_validators import AfterValidator, BeforeValidator
from rattler import MatchSpec

from wt_compiler._models import _AllowArbitraryAndForbidExtra, _ForbidExtra
from wt_compiler.jsonschema import ReactJSONSchemaFormOverrides
from wt_compiler.requirements import CONDA_FORGE_CHANNEL, ChannelType, NamelessMatchSpecType
from wt_compiler.util import rsplit_importable_reference, validate_importable_reference

# Type aliases
ImportableReference = Annotated[str, AfterValidator(validate_importable_reference)]


class TaskTag(str, Enum):
    """Tags for categorizing tasks."""

    io = "io"


class KnownTask(BaseModel):
    """Metadata for a known/registered task function.

    This represents a task that has been discovered via the registry.
    The json_schema field contains the JSON schema for the task's parameters,
    which is obtained from wt-registry CLI output (no direct import needed).
    """

    importable_reference: ImportableReference
    tags: list[TaskTag] = Field(default_factory=list)
    registry_ref: int = 0
    json_schema: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None

    @property
    def anchor(self) -> str:
        """Get the module path from the importable reference."""
        return rsplit_importable_reference(self.importable_reference)[0]

    @property
    def function_name(self) -> str:
        """Get the function name from the importable reference."""
        return rsplit_importable_reference(self.importable_reference)[1]

    @property
    def safe_reference(self) -> str:
        """Get a safe reference name for code generation.

        Adds a suffix if registry_ref > 0 to handle duplicate names.
        """
        return (
            f"{self.function_name}_{self.registry_ref}"
            if self.registry_ref > 0
            else self.function_name
        )

    def parameters_jsonschema(self, omit_args: list[str] | None = None) -> dict[str, Any]:
        """Get JSON schema for task parameters.

        Args:
            omit_args: List of argument names to exclude from schema

        Returns:
            JSON schema dict for the task's parameters

        Examples:
            >>> task = KnownTask(
            ...     importable_reference="mymodule.my_func",
            ...     json_schema={"properties": {"x": {"type": "int"}, "y": {"type": "str"}},
            ...                  "required": ["x", "y"]}
            ... )
            >>> schema = task.parameters_jsonschema(omit_args=["y"])
            >>> "x" in schema["properties"]
            True
            >>> "y" in schema["properties"]
            False
        """
        schema = self.json_schema.copy()

        # Add description if available
        if self.description is not None and "description" not in schema:
            schema["description"] = self.description

        # Filter out omitted args
        if omit_args and "properties" in schema:
            schema["properties"] = {
                arg: schema["properties"][arg]
                for arg in schema["properties"]
                if arg not in omit_args
            }
            if "required" in schema:
                schema["required"] = [
                    arg for arg in schema.get("required", []) if arg not in omit_args
                ]

        return schema

    def parameters_notebook(self, omit_args: list[str] | None = None) -> str:
        """Generate parameter dict code for Jupyter notebooks.

        Args:
            omit_args: List of argument names to exclude

        Returns:
            Python code string for parameter dict

        Examples:
            >>> task = KnownTask(
            ...     importable_reference="mymodule.my_func",
            ...     json_schema={"properties": {"x": {"type": "int"}, "y": {"type": "str"}}}
            ... )
            >>> notebook = task.parameters_notebook(omit_args=["y"])
            >>> "x=..." in notebook
            True
        """
        if "properties" not in self.json_schema:
            return "dict()"

        params = "dict(\n"
        for arg in self.json_schema["properties"]:
            if omit_args and arg in omit_args:
                continue
            params += f"    {arg}=...,\n"
        params += ")"
        return params


# Placeholder for discovered tasks - will be populated by discovery.py
known_tasks: dict[str, dict[str, KnownTask]] = {}


def _resolve_task_from_name_or_reference(s: str) -> KnownTask:
    """Resolve a KnownTask from either the task name or a fully qualified path.

    Args:
        s: Either a task name or a fully qualified importable reference

    Returns:
        The resolved KnownTask

    Raises:
        ValueError: If the task is not found or if duplicate tasks need qualification

    Examples:
        >>> # Assuming known_tasks is populated:
        >>> # _resolve_task_from_name_or_reference('my_task')  # doctest: +SKIP
        >>> # _resolve_task_from_name_or_reference('mypackage.tasks.my_task')  # doctest: +SKIP
    """
    if "." in s:
        anchor, task_name = rsplit_importable_reference(s)
        if task_name not in known_tasks:
            raise ValueError(f"Task '{task_name}' not found in known tasks")
        if anchor not in known_tasks[task_name]:
            raise ValueError(
                f"Task '{task_name}' not found in module '{anchor}'. "
                f"Available modules: {list(known_tasks[task_name].keys())}"
            )
        return known_tasks[task_name][anchor]
    else:
        if s not in known_tasks:
            raise ValueError(f"Task '{s}' not found in known tasks")
        list_of_tasks_by_name = list(known_tasks[s].values())
        if len(list_of_tasks_by_name) > 1:
            raise ValueError(
                f"Multiple tasks named '{s}' found. "
                "Duplicate tasks must be fully qualified with their module path. "
                f"Available modules: {list(known_tasks[s].keys())}"
            )
        else:
            return list_of_tasks_by_name[0]


# Workflow variable models


class _WorkflowVariable(BaseModel):
    """Base class for workflow variables."""

    value: str

    if TYPE_CHECKING:
        # Ensure type checkers see the correct return type
        def model_dump(  # type: ignore[override]
            self,
            *,
            mode: Literal["json", "python"] | str = "python",
            include: Any = None,
            exclude: Any = None,
            by_alias: bool = False,
            exclude_unset: bool = False,
            exclude_defaults: bool = False,
            exclude_none: bool = False,
            round_trip: bool = False,
            warnings: bool = True,
        ) -> str: ...


class TaskIdVariable(_WorkflowVariable):
    """A variable that references the return value of another task in the workflow."""

    suffix: Literal["return"]

    @model_serializer
    def serialize(self) -> str:
        """Serialize as just the task ID."""
        return self.value


class EnvVariable(_WorkflowVariable):
    """A variable that references an environment variable."""

    @model_serializer()
    def serialize(self) -> str:
        """Serialize as os.environ access."""
        return f'os.environ["{self.value}"]'


class InlineValue(BaseModel):
    """A variable that references a JSON-serializable inline value."""

    value: str | list[Any] | dict[str, Any] | float | int | bool | None

    @model_serializer
    def serialize(self) -> dict[str, str | bool]:
        """Serialize inline value for template use."""
        return {
            "asstr": (f"'{self.value}'" if isinstance(self.value, str) else f"{self.value}"),
            "is_inline_value": True,
        }


def _is_wrapped_variable(s: str) -> bool:
    """Check if a string is a wrapped variable reference."""
    return s.startswith("${{") and s.endswith("}}")


def _parse_variable(s: str) -> TaskIdVariable | EnvVariable:
    """Parse a variable string into the appropriate variable type."""
    if not _is_wrapped_variable(s):
        raise ValueError(
            f"`{s}` is not a valid variable. Variables must be wrapped in `${{{{ }}}}`."
        )
    inner = s.replace("${{", "").replace("}}", "").strip()
    match inner.split("."):
        case ["workflow", task_id, "return"]:
            return TaskIdVariable(value=task_id, suffix="return")
        case ["env", env_var_name]:
            return EnvVariable(value=env_var_name)
        case _:
            raise ValueError(
                "Unrecognized variable format. Expected one of: "
                "`${{ workflow.<task_id>.<suffix> }}`, "
                "`${{ env.<ENV_VAR_NAME> }}`."
            )


def _parse_variables(
    s: str | list[str],
) -> TaskIdVariable | EnvVariable | list[TaskIdVariable | EnvVariable]:
    """Parse one or more variable strings."""
    if isinstance(s, str):
        return _parse_variable(s)
    return [_parse_variable(v) for v in s]


# Validation functions


def _is_identifier(s: str) -> str:
    """Validate that a string is a valid Python identifier."""
    if not s.isidentifier():
        raise ValueError(f"`{s}` is not a valid python identifier.")
    return s


def _is_not_reserved(s: str) -> str:
    """Validate that a string is not a Python keyword or builtin."""
    assert _is_identifier(s)
    if keyword.iskeyword(s):
        raise ValueError(f"`{s}` is a python keyword.")
    if s in dir(builtins):
        raise ValueError(f"`{s}` is a built-in python function.")
    return s


def _is_valid_task_instance_id(s: str) -> str:
    """Validate task instance ID constraints."""
    if s in known_tasks:
        raise ValueError(f"`{s}` is a registered known task name.")
    if len(s) > 32:
        raise ValueError(f"`{s}` is too long; max length is 32 characters.")
    return s


def _is_known_task_name(s: str) -> str:
    """Validate that a string is a known task name."""
    if s not in known_tasks:
        raise ValueError(f"`{s}` is not a registered known task name.")
    return s


def _is_valid_spec_name(s: str) -> str:
    """Validate spec name constraints."""
    if len(s) > 64:
        raise ValueError(f"`{s}` is too long; max length is 64 characters.")
    return s


# Workflow variable type annotations

WorkflowVariable = Annotated[TaskIdVariable | EnvVariable, BeforeValidator(_parse_variables)]


def _serialize_variables(v: list[WorkflowVariable]) -> dict[str, str | list[str]]:
    """Serialize a list of workflow variables to a string for use in templating.

    Args:
        v: List of WorkflowVariable instances

    Returns:
        Dictionary with 'asstr' and 'aslist' keys for template use

    Examples:
        >>> var1 = TaskIdVariable(value="task1", suffix="return")
        >>> _serialize_variables([var1])  # doctest: +SKIP
        {'asstr': 'task1', 'aslist': ['task1']}
    """
    return {
        "asstr": (
            v[0].model_dump() if len(v) == 1 else f"[{', '.join(var.model_dump() for var in v)}]"
        ),
        "aslist": [var.model_dump() for var in v],
    }


def _singleton_or_list_aslist(s: Any | list[Any]) -> list[Any]:
    """Convert singleton to list or pass through list."""
    return [s] if not isinstance(s, list) else s


Vars = Annotated[
    list[WorkflowVariable],
    BeforeValidator(_singleton_or_list_aslist),
    PlainSerializer(_serialize_variables, return_type=dict[str, str | list[str]]),
]

TaskInstanceId = Annotated[
    str,
    AfterValidator(_is_not_reserved),
    AfterValidator(_is_valid_task_instance_id),
]
KnownTaskName = Annotated[str, AfterValidator(_is_known_task_name)]
KnownTaskArgName = Annotated[str, AfterValidator(_is_identifier)]


def _vars_or_inline_value(v: Any) -> str:
    """Discriminator for VarsOrInlineValue union."""
    match v:
        case str() if _is_wrapped_variable(v):
            return "vars"
        case list() if (
            len(v) > 0
            and all(isinstance(i, str) for i in v)
            and all(_is_wrapped_variable(i) for i in v)
        ):
            return "vars"
        case _:
            return "inline_value"


def _serialize_variables_or_inline_value(
    v: list[WorkflowVariable] | InlineValue,
) -> dict[str, str | list[str]] | dict[str, str | bool]:
    """Serialize either variables or inline values."""
    if isinstance(v, InlineValue):
        return v.model_dump()
    return _serialize_variables(v)


InlineValueType = Annotated[InlineValue, BeforeValidator(lambda v: InlineValue(value=v))]
VarsOrInlineValue = Annotated[
    Annotated[InlineValueType, PydanticTag("inline_value")] | Annotated[Vars, PydanticTag("vars")],
    Discriminator(_vars_or_inline_value),
    PlainSerializer(
        _serialize_variables_or_inline_value,
        return_type=dict[str, str | list[str] | bool],
    ),
]


def _variable_values_dict_or_vars_or_inline_value(v: Any) -> str:
    """Discriminator for DictOrVarsOrInlineValue union."""
    match v:
        case dict() if any(isinstance(i, str) and (_is_wrapped_variable(i)) for i in v.values()):
            return "inline_dict"
        case _:
            return "vars_or_inline_value"


class VariableValuesDict(BaseModel):
    """A dictionary with variable values."""

    value: dict[str, VarsOrInlineValue]

    @model_serializer
    def serialize(
        self,
    ) -> dict[str, dict[str, Any] | str | bool]:
        """Serialize for template use."""
        return {
            "asstr": (
                "{"
                + ", ".join(
                    f"'{k}': {_serialize_variables_or_inline_value(v).get('asstr')}"
                    for k, v in self.value.items()
                )
                + "}"
            ),
            "asdict": ({k: _serialize_variables_or_inline_value(v) for k, v in self.value.items()}),
            "has_variable_values": True,
        }


def _serialize_dict_or_variables_or_inline_value(
    v: VariableValuesDict | VarsOrInlineValue,
) -> dict[str, str | list[str]] | dict[str, str | bool] | dict[str, dict[str, Any] | str | bool]:
    """Serialize dict or variables or inline values."""
    if isinstance(v, VariableValuesDict):
        return v.model_dump()
    return _serialize_variables_or_inline_value(v)


VariableValuesDictType = Annotated[
    VariableValuesDict, BeforeValidator(lambda v: VariableValuesDict(value=v))
]
DictOrVarsOrInlineValue = Annotated[
    Annotated[VariableValuesDictType, PydanticTag("inline_dict")]
    | Annotated[VarsOrInlineValue, PydanticTag("vars_or_inline_value")],
    Discriminator(_variable_values_dict_or_vars_or_inline_value),
    PlainSerializer(
        _serialize_dict_or_variables_or_inline_value,
        return_type=dict[str, str | list[str]]
        | dict[str, str | bool]
        | dict[str, dict[str, Any] | str | bool],
    ),
]
PartialKwargs: TypeAlias = dict[KnownTaskArgName, DictOrVarsOrInlineValue]
SpecId = Annotated[str, AfterValidator(_is_not_reserved), AfterValidator(_is_valid_spec_name)]
ParallelOpArgNames = Annotated[list[KnownTaskArgName], BeforeValidator(_singleton_or_list_aslist)]


class _ParallelOperation(_ForbidExtra):
    """Base class for parallel operations (map and mapvalues)."""

    argnames: ParallelOpArgNames = Field(default_factory=list)
    argvalues: Vars = Field(default_factory=list)

    @model_validator(mode="after")
    def both_fields_required_if_either_given(self) -> "_ParallelOperation":
        """Validate that both argnames and argvalues are provided together."""
        if bool(self.argnames) != bool(self.argvalues):
            raise ValueError("Both `argnames` and `argvalues` must be provided if either is given.")
        return self

    def __bool__(self) -> bool:
        """Return False if both argnames and argvalues are empty.

        Lets us use empty _ParallelOperation models as their own defaults in TaskInstance,
        while still allowing boolean checks such as `if self.map`, `if self.mapvalues`, etc.
        """
        return bool(self.argnames) and bool(self.argvalues)

    @property
    def all_dependencies_dict(self) -> dict[str, list[str]]:
        """Get all dependencies as a dictionary."""
        return {
            arg: [var.value for var in self.argvalues if isinstance(var, TaskIdVariable)]
            for arg in self.argnames
        }


class MapOperation(_ParallelOperation):
    """A map operation to apply a task to an iterable of values."""

    pass


class MapValuesOperation(_ParallelOperation):
    """A mapvalues operation to apply a task to an iterable of key-value pairs."""

    pass


class SkipIf(_ForbidExtra):
    """A set of skipif conditions for a task instance."""

    conditions: list[ImportableReference | KnownTaskName] = Field(default_factory=list)
    unpack_depth: int = Field(default=1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def known_tasks_list(self) -> list[KnownTask]:
        """Resolve all condition task names to KnownTask instances."""
        return [
            _resolve_task_from_name_or_reference(known_task_name)
            for known_task_name in self.conditions
        ]

    @model_validator(mode="after")
    def ensure_known_tasks(self) -> "SkipIf":
        """Validate that all tasks in conditions can be resolved."""
        try:
            _ = self.known_tasks_list
        except ValueError as e:
            raise e
        return self


class TaskInstance(_ForbidExtra):
    """A task instance in a workflow.

    Represents a single task execution with its configuration including
    static arguments (partial), parallel operations (map/mapvalues),
    and conditional execution (skipif).
    """

    name: str = Field(
        description="""\
        A human-readable name, e.g. 'Draw Ecomaps for Each Input Geodataframe'.
        """,
        default="",
    )
    id: TaskInstanceId = Field(
        description="""\
        Unique identifier for this task instance. This will be used as the name to which
        the result of this task is assigned in the compiled DAG. As such, it should be a
        valid python identifier and it cannot collide with any: Python keywords, Python
        builtins, or any registered known task names. It must also be unique within the
        context of all task instance `id`s in the workflow. The maximum length is 32 chars.
        """,
    )
    known_task_name: ImportableReference | KnownTaskName = Field(
        alias="task",
        description="""\
        The name of the known task to be executed. This must be a registered known task name.
        """,
    )
    skipif: SkipIf | None = Field(
        default=None,
        description="""\
        A set of skipif conditions for this task instance. This is a list of known task names
        that are used to determine if this task instance should be skipped. The task instance
        will be skipped if any of the conditions are met. Optional, defaults to None.
        """,
    )
    partial: PartialKwargs = Field(
        default_factory=dict,
        description="""\
        Static keyword arguments to be passed to every invocation of the the task. This is a
        dict with keys which are the names of the arguments on the known task, and values which
        are the values to be passed. The values can be variable references or lists of variable
        references. The variable reference(s) may be in the form `${{ workflow.<task_id>.return }}`
        for task return values, or `${{ env.<ENV_VAR_NAME> }}` for environment variables.

        For more details, see `Task.partial` in the `decorators` module.
        """,
    )
    map: MapOperation = Field(
        default_factory=MapOperation,
        description="""\
        A `map` operation to apply the task to an iterable of values. The `argnames` must be a
        single string, or a list of strings, which correspond to name(s) of argument(s) in the
        task function signature. The `argvalues` must be a variable reference of form
        `${{ workflow.<task_id>.return }}` (where the task id is the id of another task in the
        workflow with an iterable return), or a list of such references (where each reference is
        non-iterable, such that the combination of those references is a flat iterable).

        For more details, see `Task.map` in the `decorators` module.
        """,
    )
    mapvalues: MapValuesOperation = Field(
        default_factory=MapValuesOperation,
        description="""\
        A `mapvalues` operation to apply the task to an iterable of key-value pairs.
        The `argnames` must be a single string, or a single-element list of strings,
        which correspond to the name of an argument on the task function signature.
        The `argvalues` must be a list of tuples where the first element of each tuple
        is the key to passthrough, and the second element is the value to transform.

        For more details, see `Task.mapvalues` in the `decorators` module.
        """,
    )

    @property
    def flattened_partial_values(self) -> list[Any | WorkflowVariable]:
        """Get all partial values as a flat list."""
        return [
            (list(var) if isinstance(var, tuple) else var)
            for dep in self.partial.values()
            for var in (
                [
                    inner_var
                    for var in dep.value.values()
                    for inner_var in var
                    if isinstance(inner_var, TaskIdVariable)
                ]
                if isinstance(dep, VariableValuesDict)
                else dep
            )
            if not isinstance(dep, InlineValue)
        ]

    @property
    def all_dependencies(self) -> list[Any | WorkflowVariable]:
        """Get all dependencies including partial, map, and mapvalues."""
        return self.flattened_partial_values + self.map.argvalues + self.mapvalues.argvalues

    @property
    def all_dependencies_dict(self) -> dict[str, list[str]]:
        """Get all dependencies as a dictionary mapping args to task IDs."""
        return (
            {
                arg: (
                    [
                        inner_var.value
                        for var in dep.value.values()
                        for inner_var in var
                        if isinstance(inner_var, TaskIdVariable)
                    ]
                    if isinstance(dep, VariableValuesDict)
                    else [var.value for var in dep if isinstance(var, TaskIdVariable)]
                )
                for arg, dep in self.partial.items()
            }
            | self.map.all_dependencies_dict
            | self.mapvalues.all_dependencies_dict
        )

    @model_validator(mode="after")
    def check_does_not_depend_on_self(self) -> "TaskInstance":
        """Validate that a task doesn't depend on itself."""
        for dep in self.all_dependencies:
            if isinstance(dep, TaskIdVariable) and dep.value == self.id:
                raise ValueError(
                    f"Task `{self.name}` has an arg dependency that references itself: "
                    f"`{dep.value}`. Task instances cannot depend on their own return values."
                )
        return self

    @model_validator(mode="after")
    def check_only_oneof_map_or_mapvalues(self) -> "TaskInstance":
        """Validate that a task uses either map or mapvalues, not both."""
        if self.map and self.mapvalues:
            raise ValueError(
                f"Task `{self.name}` cannot have both `map` and `mapvalues` set. "
                "Please choose one or the other."
            )
        return self

    @field_validator("name", mode="before")
    def coerce_none_to_empty_string(cls, value: Any) -> str:
        """Convert None to empty string for name field."""
        return "" if value is None else value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def known_task(self) -> KnownTask:
        """Resolve the known_task_name to a KnownTask instance."""
        return _resolve_task_from_name_or_reference(self.known_task_name)

    @model_validator(mode="after")
    def ensure_known_task(self) -> "TaskInstance":
        """Validate that the known task can be resolved."""
        try:
            _ = self.known_task
        except ValueError as e:
            raise e
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def method(self) -> str:
        """Get the execution method: 'map', 'mapvalues', or 'call'."""
        return "map" if self.map else None or "mapvalues" if self.mapvalues else None or "call"


class TaskGroup(_ForbidExtra):
    """A group of related tasks in the workflow."""

    title: str
    description: str
    tasks: list[TaskInstance]
    type: Literal["task-group"] = "task-group"


def _group_or_instance(v: Any) -> str:
    """Discriminator function to determine if entry is a group or instance."""
    msg = "The `workflow` field must be a list of task instances or task groups."
    # Handle already-validated model instances
    if isinstance(v, TaskInstance):
        return "instance"
    if isinstance(v, TaskGroup):
        return "group"
    if not isinstance(v, dict):
        raise ValueError(msg)
    match v:
        case _ if v.get("type") == "task-group":
            return "group"
        case _ if all(k in v for k in ("id", "task")):
            return "instance"
        case _:
            raise ValueError(msg)


class SpecRequirement(_AllowArbitraryAndForbidExtra):
    """A requirement specification for the workflow.

    Can be constructed with separate fields or a single requirement string:
        SpecRequirement(name="package", version=">=1.0", channel="conda-forge")
        SpecRequirement(requirement="package>=1.0.0")
    """

    name: str
    version: NamelessMatchSpecType
    channel: ChannelType = Field(default_factory=lambda: CONDA_FORGE_CHANNEL)

    @model_validator(mode="before")
    @classmethod
    def parse_requirement_string(cls, values: Any) -> Any:
        """Parse a requirement string like 'package>=1.0.0' into name/version/channel."""
        if isinstance(values, dict) and "requirement" in values:
            req_str = values.pop("requirement")
            match_spec = MatchSpec(req_str)
            # match_spec.name returns PackageNameMatcher, use .normalized to get string
            values["name"] = match_spec.name.normalized if match_spec.name else None
            values["version"] = str(match_spec.version) if match_spec.version else "*"
            if match_spec.channel:
                values["channel"] = match_spec.channel.name or match_spec.channel.base_url
        return values


class TaskInstanceDefaults(_ForbidExtra):
    """Defaults for task instances in the workflow.

    These options, if given, will be applied to any task instance in the workflow
    that does not declare its own value for the option of the same name.
    """

    skipif: SkipIf | None = Field(default=None)


class Spec(_ForbidExtra):
    """Complete workflow specification.

    This is the root model for a workflow spec.yaml file, containing
    all task instances, requirements, and configuration.
    """

    id: SpecId = Field(
        description="""\
        A unique identifier for this workflow. This will be used to identify the compiled DAG.
        It should be a valid python identifier and cannot collide with any: Python identifiers,
        Python keywords, or Python builtins. The maximum length is 64 chars.
        """
    )
    requirements: list[SpecRequirement]
    rjsf_overrides: ReactJSONSchemaFormOverrides = Field(
        alias="rjsf-overrides",
        default_factory=ReactJSONSchemaFormOverrides,
    )
    task_instance_defaults: TaskInstanceDefaults = Field(
        alias="task-instance-defaults",
        default_factory=TaskInstanceDefaults,
    )
    workflow: list[
        Annotated[
            Annotated[TaskInstance, PydanticTag("instance")]
            | Annotated[TaskGroup, PydanticTag("group")],
            Discriminator(_group_or_instance),
        ]
    ] = Field(
        description="A list of task groups and/or instances that define the workflow.",
    )

    @property
    def sha256(self) -> str:
        """Generate SHA256 hash of the workflow (excluding requirements)."""
        return hashlib.sha256(self.model_dump_json(exclude={"requirements"}).encode()).hexdigest()

    @property
    def requires_local_release_artifacts(self) -> bool:
        """Check if any requirements use local file:// channels."""
        return any(r.channel.base_url.startswith("file://") for r in self.requirements)

    @property
    def _flat_task_instances_with_defaults(self) -> list[TaskInstance]:
        """Get all task instances with defaults applied."""
        all_task_instances = [
            task_instance
            for group_or_instance in self.workflow
            for task_instance in (
                group_or_instance.tasks
                if isinstance(group_or_instance, TaskGroup)
                else [group_or_instance]
            )
        ]
        for ti in all_task_instances:
            if ti.skipif is None:
                ti.skipif = self.task_instance_defaults.skipif
        return all_task_instances

    @computed_field  # type: ignore[prop-decorator]
    @property
    def flat_workflow(self) -> list[TaskInstance]:
        """Get all task instances as a flat list."""
        return self._flat_task_instances_with_defaults

    @property
    def all_task_ids(self) -> dict[str, str]:
        """Get mapping of all task IDs to task names."""
        return {task_instance.id: task_instance.name for task_instance in self.flat_workflow}

    @model_validator(mode="after")
    def check_task_ids_dont_collide_with_spec_id(self) -> "Spec":
        """Validate that no task ID matches the spec ID."""
        if self.id in self.all_task_ids.keys():
            name = next(name for id, name in self.all_task_ids.items() if id == self.id)
            raise ValueError(
                "Task `id`s cannot be the same as the spec `id`. "
                f"The `id` of task `{name}` is `{self.id}`, which is the same as the spec `id`. "
                "Please choose a different `id` for this task."
            )
        return self

    @model_validator(mode="after")
    def check_task_ids_unique(self) -> "Spec":
        """Validate that all task IDs are unique."""
        id_keyed_dict: dict[str, int] = dict.fromkeys(self.all_task_ids.keys(), 0)
        for ti in self.flat_workflow:
            id_keyed_dict[ti.id] += 1
        dupes = {id: count for id, count in id_keyed_dict.items() if count > 1}
        if dupes:
            raise ValueError(
                "All task instance `id`s must be unique in the workflow. "
                f"Found duplicate ids: {','.join(dupes.keys())}"
            )
        return self

    @model_validator(mode="after")
    def check_all_task_id_deps_use_actual_ids_of_other_tasks(self) -> "Spec":
        """Validate that all task ID dependencies reference actual tasks."""
        all_ids = [task_instance.id for task_instance in self.flat_workflow]
        for ti_id, deps in self.task_instance_dependencies.items():
            for d in deps:
                if d not in all_ids:
                    raise ValueError(
                        f"Task `{ti_id}` has an arg dependency `{d}` that is "
                        f"not a valid task id. Valid task ids for this workflow are: {all_ids}"
                    )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def task_instance_dependencies(self) -> dict[str, list[str]]:
        """Get all task dependencies as a dictionary."""
        return {
            task_instance.id: [
                d.value for d in task_instance.all_dependencies if isinstance(d, TaskIdVariable)
            ]
            for task_instance in self.flat_workflow
        }

    @model_validator(mode="after")
    def check_task_instances_are_in_topological_order(self) -> "Spec":
        """Validate that tasks are in topological order (dependencies come first)."""
        seen_task_instance_ids = set()
        for task_instance_id, deps in self.task_instance_dependencies.items():
            seen_task_instance_ids.add(task_instance_id)
            for dep_id in deps:
                if dep_id not in seen_task_instance_ids:
                    dep_name = next(ti.name for ti in self.flat_workflow if ti.id == dep_id)
                    task_instance_name = next(
                        ti.name for ti in self.flat_workflow if ti.id == task_instance_id
                    )
                    raise ValueError(
                        f"Task instances are not in topological order. "
                        f"`{task_instance_name}` depends on `{dep_name}`, "
                        f"but `{dep_name}` is defined after `{task_instance_name}`."
                    )
        return self


# DAG types for code generation
DagTypes = Literal["jupytext", "async", "sequential"]
