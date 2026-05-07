"""Workflow compiler for generating DAG artifacts from specifications.

NOTE: This is a streamlined initial implementation. The full compiler from
legacy ecoscope-workflows-core is ~1300 lines. This version includes the core
compilation workflow with placeholders for complex features that need expansion.

TODO areas for expansion:
- Complete all DagCompiler methods (many are simplified stubs)
- Add full JSON schema generation for parameters
- Add complete template rendering for all DAG types
- Add graph visualization with pydot
- Add comprehensive fingerprinting
- Add version management logic
"""

import hashlib
import io
import json
import os
import pathlib
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pydot as dot
import ruamel.yaml
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field, computed_field
from rattler import Channel, MatchSpec, NamelessMatchSpec

from wt_compiler.artifacts import (
    Dags,
    Feature,
    PackageDirectory,
    PixiToml,
    PixiWorkspace,
    Tests,
    WorkflowArtifacts,
)
from wt_compiler.artifacts import (
    Environment as PixiEnvironment,
)
from wt_compiler.discovery import populate_known_tasks
from wt_compiler.formatting import ruff_formatted
from wt_compiler.jsonschema import ReactJSONSchemaFormConfiguration, find_referenced_defs
from wt_compiler.progress import spinner
from wt_compiler.requirements import (
    CHANNELS,
    CONDA_FORGE_CHANNEL,
    CUSTOM_LOCAL_CHANNEL,
    CUSTOM_RELEASE_CHANNEL,
    LOCAL_CHANNEL,
    MICROSOFT_CHANNEL,
    RELEASE_CHANNEL,
    WT_LOCAL_CHANNEL,
)
from wt_compiler.spec import (
    DagTypes,
    KnownTaskArgName,
    PyPIRequirement,
    Spec,
    SpecRequirement,
    TaskGroup,
    TaskInstance,
    TaskInstanceId,
    TaskTag,
    _conda_or_pypi,
)

yaml = ruamel.yaml.YAML(typ="safe")

# Template directory
TEMPLATES = pathlib.Path(__file__).parent / "templates"


def _remove_functionally_irrelevant_keys(
    data: dict[str, Any] | list[Any],
) -> dict[str, Any] | list[Any] | Any:
    """Remove keys from JSON schema that are irrelevant to fingerprinting.

    This removes documentation-related keys like title, description, default, and uiSchema
    to get an accurate hash of the functional structure.

    Args:
        data: JSON schema dict or list

    Returns:
        Cleaned data structure

    Examples:
        >>> schema = {"title": "My Field", "type": "string", "default": "foo"}
        >>> cleaned = _remove_functionally_irrelevant_keys(schema)
        >>> "title" in cleaned
        False
        >>> "type" in cleaned
        True
    """
    if isinstance(data, dict):
        return {
            key: _remove_functionally_irrelevant_keys(value)
            for key, value in data.items()
            if key not in {"title", "description", "default", "uiSchema"}
        }
    elif isinstance(data, list):
        return [_remove_functionally_irrelevant_keys(item) for item in data]
    else:
        return data


def _build_installed_requirements(
    spec_requirements: list[SpecRequirement],
    records: list[Any],  # list[RepoDataRecord] from rattler solve()
) -> list[SpecRequirement]:
    """Build installed requirements from spec requirements and solved records.

    For each spec requirement, finds the solved version from records and creates
    a new SpecRequirement with the exact pinned version and resolved channel.

    Args:
        spec_requirements: Original spec requirements
        records: Solved RepoDataRecord objects from rattler

    Returns:
        List of SpecRequirement with pinned versions (e.g., ==1.2.3)

    Examples:
        >>> # records = [...]  # RepoDataRecord from rattler solve  # doctest: +SKIP
        >>> # reqs = [SpecRequirement(requirement="pandas>=2.0")]  # doctest: +SKIP
        >>> # installed = _build_installed_requirements(reqs, records)  # doctest: +SKIP
        >>> # installed[0].version.version  # "==2.2.3"  # doctest: +SKIP
    """
    # Build lookup: normalized package name -> version string
    solved_versions: dict[str, tuple[str, str]] = {}
    for r in records:
        name = str(r.name.normalized)
        version = str(r.version)
        channel = str(r.channel)
        solved_versions[name] = (version, channel)

    installed: list[SpecRequirement] = []
    for req in spec_requirements:
        if req.name in solved_versions:
            version, channel = solved_versions[req.name]
            installed.append(
                SpecRequirement(
                    name=req.name,
                    version=f"=={version}",  # type: ignore[arg-type]
                    channel=channel,  # type: ignore[arg-type]
                )
            )

    return installed


class Fingerprint(BaseModel):
    """A fingerprint of the spec and its artifacts.

    Used for version management and change detection.
    """

    spec: Spec
    wa: WorkflowArtifacts
    installed_requirements: list[SpecRequirement] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def spec_sha256(self) -> str:
        """SHA256 hash of the spec."""
        return self.spec.sha256

    @computed_field  # type: ignore[prop-decorator]
    @property
    def params_sha256(self) -> str:
        """SHA256 hash of the parameters model.

        This is used to determine if parameters have changed in a way that
        would require users to reconfigure existing workflows.
        """
        cleaned = _remove_functionally_irrelevant_keys(self.wa.package.params_json)
        return hashlib.sha256(json.dumps(cleaned, sort_keys=True).encode()).hexdigest()

    def _get_artifacts_sha256(self, exclude: set[str]) -> str:
        """Get SHA256 hash of artifacts with specific exclusions."""
        unsortedjson = self.wa.model_dump_json(
            exclude={"spec_relpath", "pydot_graph", "readme_md"} | exclude
        ).encode()
        sortedjson = json.dumps(json.loads(unsortedjson), sort_keys=True)
        return hashlib.sha256(sortedjson.encode()).hexdigest()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def artifacts_sha256_basic(self) -> str:
        """Basic artifact hash excluding dockerfile and pixi.toml."""
        return self._get_artifacts_sha256(exclude={"dockerfile", "pixi_toml"})

    @computed_field  # type: ignore[prop-decorator]
    @property
    def artifacts_sha256_strict(self) -> str:
        """Strict artifact hash including all files."""
        return self._get_artifacts_sha256(exclude=set())

    def to_yaml(self) -> str:
        """Serialize fingerprint to YAML."""
        stream = io.StringIO()
        yaml.dump(self.model_dump(exclude={"spec", "wa"}), stream)
        return stream.getvalue()


class DagCompiler(BaseModel):
    """Main compiler class for converting workflow specs to DAG artifacts.

    This class handles the complete compilation pipeline:
    1. Parse workflow specification
    2. Discover tasks from requirements
    3. Generate parameter schemas
    4. Render DAG code from templates
    5. Generate pixi.toml, Dockerfile, tests
    6. Create complete workflow package
    """

    spec: Spec
    wt_runner_channel: str | None = None
    wt_pypi_deps: dict[str, str | dict[str, Any]] | None = None
    variant: str | None = None
    jinja_templates_dir: pathlib.Path = TEMPLATES
    pkg_name_prefix: str = "wt"
    results_env_var: str = "WT_RESULTS"

    def get_dag_config(self, dag_type: DagTypes, mock_io: bool) -> dict[str, Any]:
        """Get configuration dict for rendering a DAG.

        Args:
            dag_type: Type of DAG to generate (async, sequential)
            mock_io: Whether to use mock I/O for testing

        Returns:
            Configuration dictionary for template rendering
        """
        return self.model_dump(
            exclude={"jinja_templates_dir"},
            context={"mock_io": mock_io},
        )

    @property
    def per_taskinstance_omit_args(
        self,
    ) -> dict[TaskInstanceId, list[KnownTaskArgName]]:
        """Get arguments to omit from parameter forms.

        For a given arg on a task instance, if it is dependent on another task's
        return value, we omit it from the user-facing parameters.

        Returns:
            Mapping of task ID to list of argument names to omit
        """
        return {
            t.id: (["return"] + list(t.partial) + list(t.map.argnames) + list(t.mapvalues.argnames))
            for t in self.spec.flat_workflow
        }

    @staticmethod
    def _props_and_defs_from_task_instance(
        t: TaskInstance,
        omit_args: list[str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Extract properties and definitions from a task instance.

        Args:
            t: TaskInstance to extract schema from
            omit_args: Arguments to omit from the schema

        Returns:
            Tuple of (properties dict, definitions dict)
        """
        props = {t.id: t.known_task.parameters_jsonschema(omit_args=omit_args)}
        defs: dict[str, Any] = {}

        for _, schema in props.items():
            schema["title"] = t.name
            if "$defs" in schema:
                # bc we've omitted some args, some defs may be unused, so exclude them
                assert isinstance(schema["$defs"], dict)
                referenced_defs = find_referenced_defs(schema)
                defs.update({k: v for k, v in schema["$defs"].items() if k in referenced_defs})
                del schema["$defs"]
        return props, defs

    @staticmethod
    def _maybe_add_ui_order(
        ui_schema: dict[str, Any], group_or_instance: dict[str, Any], name: str
    ) -> None:
        """Explicitly set the display order for properties.

        Adds ui:order for tasks with multiple args and task groups with multiple tasks.

        Args:
            ui_schema: UI schema dict to update
            group_or_instance: Group or instance schema
            name: Name of the group/instance
        """
        # ui:order is redundant in the case of 0 or 1 prop
        if len(group_or_instance.get("properties", {})) > 1:
            ui_schema[name] = {"ui:order": list(group_or_instance["properties"])}

        if group_or_instance.get("ecoscope:task_group"):
            for task_name in group_or_instance.get("properties", {}):
                task = group_or_instance["properties"][task_name]
                if len(task.get("properties", {})) > 1:
                    # Need to check this because we can have a single task within a group
                    # and if so we would not have inited ui_schema[name] yet
                    if not ui_schema.get(name):
                        ui_schema[name] = {}
                    ui_schema[name][task_name] = {"ui:order": list(task["properties"])}

    def get_params_jsonschema(self, flat: bool = True) -> ReactJSONSchemaFormConfiguration:
        """Generate JSON schema for workflow parameters.

        Args:
            flat: If True, flatten task groups into flat structure.
                 If False, preserve task group hierarchy.

        Returns:
            RJSF configuration with schema and uiSchema

        Examples:
            >>> from wt_compiler.spec import Spec
            >>> # spec = Spec(...)  # doctest: +SKIP
            >>> # compiler = DagCompiler(spec=spec)  # doctest: +SKIP
            >>> # schema = compiler.get_params_jsonschema()  # doctest: +SKIP
        """
        properties: dict[str, Any] = {}
        definitions: dict[str, Any] = {}
        uiSchema: dict[str, Any] = {}

        if flat:
            # Flat structure - all tasks at top level
            for t in self.spec.flat_workflow:
                omit_args = self.per_taskinstance_omit_args.get(t.id, [])
                props, defs = self._props_and_defs_from_task_instance(t, omit_args)
                if props[t.id].get("properties"):
                    properties |= props
                    definitions |= defs
                    self._maybe_add_ui_order(uiSchema, props[t.id], t.id)
        else:
            # Hierarchical structure - preserve task groups
            for group_or_instance in self.spec.workflow:
                match group_or_instance:
                    case TaskGroup(title=title, description=description, tasks=task_instances):
                        grouped_props: dict[str, Any] = {
                            "type": "object",
                            "description": description,
                            "ecoscope:task_group": True,
                            "properties": {},
                        }
                        for t in task_instances:
                            omit_args = self.per_taskinstance_omit_args.get(t.id, [])
                            props, defs = self._props_and_defs_from_task_instance(t, omit_args)
                            if props[t.id].get("properties"):
                                grouped_props["properties"] |= props
                                definitions |= defs
                        if grouped_props["properties"]:
                            properties[title] = grouped_props
                            self._maybe_add_ui_order(uiSchema, grouped_props, title)
                    case TaskInstance() as t:
                        omit_args = self.per_taskinstance_omit_args.get(t.id, [])
                        props, defs = self._props_and_defs_from_task_instance(t, omit_args)
                        if props[t.id].get("properties"):
                            properties |= props
                            definitions |= defs
                            self._maybe_add_ui_order(uiSchema, props[t.id], t.id)

        # Set top-level ui:order
        uiSchema["ui:order"] = list(properties)

        # Create base configuration
        config = ReactJSONSchemaFormConfiguration(
            title=None,
            properties=properties,
            uiSchema=uiSchema,
            **{"$defs": definitions},  # type: ignore[arg-type]
        )

        return config

    def get_params_fillable_yaml(self) -> str:
        """Generate a fillable YAML template for parameters.

        Returns:
            YAML string with placeholder values
        """
        # TODO: Implement based on params schema
        return "# TODO: Generate fillable params YAML\n"

    def get_pixi_toml(self) -> PixiToml:
        """Generate pixi.toml for the workflow.

        Builds a complete pixi.toml with:
        - Dynamic channels based on which channels are used in requirements
        - System requirements (linux = "4.4.0" for Docker compatibility)
        - Dependencies with channel specified per dependency
        - feature.runner with wt-runner
        - feature.test with test dependencies and tasks
        - Environments: default, runner, test
        - Tasks: docker-build (if local artifacts) and workflow CLI

        Returns:
            PixiToml model with all dependencies and configuration
        """
        # Separate conda and pypi requirements
        conda_reqs = self.spec.conda_requirements
        pypi_reqs = self.spec.pypi_requirements

        # Initialize pypi-dependencies from spec's PyPI requirements
        pypi_dependencies: dict[str, str | dict[str, Any]] = {}
        for pypi_req in pypi_reqs:
            pypi_dependencies[pypi_req.name] = pypi_req.to_pixi_dict()

        # 1. Build channels list dynamically based on which channels are in requirements
        channels: list[str] = []
        if any(r.channel.base_url == LOCAL_CHANNEL.base_url for r in conda_reqs):
            channels.append(LOCAL_CHANNEL.base_url)
        if any(r.channel.base_url == WT_LOCAL_CHANNEL.base_url for r in conda_reqs):
            channels.append(WT_LOCAL_CHANNEL.base_url)
        if any(r.channel.base_url == CUSTOM_LOCAL_CHANNEL.base_url for r in conda_reqs):
            channels.append(CUSTOM_LOCAL_CHANNEL.base_url)
        if any(r.channel.base_url == CUSTOM_RELEASE_CHANNEL.base_url for r in conda_reqs):
            channels.append(CUSTOM_RELEASE_CHANNEL.base_url)
        if (
            self.wt_runner_channel
            and self.wt_runner_channel.startswith("file://")
            and self.wt_runner_channel not in channels
        ):
            channels.append(self.wt_runner_channel)
        # Always add standard channels at the end
        # Note: name can be None for custom channels but not for these standard channels
        assert CONDA_FORGE_CHANNEL.name is not None
        assert MICROSOFT_CHANNEL.name is not None
        channels += [RELEASE_CHANNEL.base_url, CONDA_FORGE_CHANNEL.name, MICROSOFT_CHANNEL.name]

        # 2. Build workspace with dynamic channels
        # (pydantic validators accept strings and parse them to Channel objects)
        workspace = PixiWorkspace(name=self.release_name, channels=channels)  # type: ignore[arg-type]

        # 3. Build dependencies with channel per dependency
        dependencies: dict[str, NamelessMatchSpec] = {}
        for r in conda_reqs:
            version_str = str(r.version.version) if r.version.version else "*"
            dependencies[r.name] = NamelessMatchSpec.from_match_spec(
                MatchSpec(f"{r.channel.base_url}::{r.name} {version_str}")
            )

        # 3b. Add cli.py runtime dependencies (used by generated cli.py)
        runner_channel = self.wt_runner_channel
        task_pkg = f"wt-task-{self.variant}" if self.variant else "wt-task"
        runner_pkg = f"wt-runner-{self.variant}" if self.variant else "wt-runner"

        cli_runtime_deps: dict[str, NamelessMatchSpec] = {
            "click": NamelessMatchSpec.from_match_spec(
                MatchSpec("conda-forge::click >=8.0.0,<9.0.0")
            ),
            "obstore": NamelessMatchSpec.from_match_spec(
                MatchSpec("conda-forge::obstore >=0.6.0,<0.7.0")
            ),
            "pydantic": NamelessMatchSpec.from_match_spec(
                MatchSpec("conda-forge::pydantic >=2.0.0,<3.0.0")
            ),
            "ruamel.yaml": NamelessMatchSpec.from_match_spec(
                MatchSpec("conda-forge::ruamel.yaml >=0.19.0,<0.20.0")
            ),
            "opentelemetry-api": NamelessMatchSpec.from_match_spec(
                MatchSpec("conda-forge::opentelemetry-api >=1.20.0,<2.0.0")
            ),
        }
        # Only add wt-task to conda deps when not using PyPI mode
        if self.wt_pypi_deps is None:
            cli_runtime_deps[task_pkg] = NamelessMatchSpec.from_match_spec(
                MatchSpec(f"{runner_channel}::{task_pkg} >=0.1.2,<1.0.0")
            )
        dependencies.update(cli_runtime_deps)

        # 4. Build feature.runner.dependencies
        runner_conda_deps: dict[str, NamelessMatchSpec] = {}
        runner_pypi_deps: dict[str, str | dict[str, Any]] = {}

        if self.wt_pypi_deps is None:
            # Conda mode: wt-runner comes from conda channel
            runner_conda_deps[runner_pkg] = NamelessMatchSpec.from_match_spec(
                MatchSpec(f"{runner_channel}::{runner_pkg} >=0.1.5,<1.0.0")
            )
        else:
            # PyPI mode: wt-runner goes in runner feature pypi-deps,
            # wt-task goes in top-level pypi-deps
            if runner_pkg in self.wt_pypi_deps:
                runner_pypi_deps[runner_pkg] = self.wt_pypi_deps[runner_pkg]
            if task_pkg in self.wt_pypi_deps:
                pypi_dependencies[task_pkg] = self.wt_pypi_deps[task_pkg]

        runner_feature = Feature(dependencies=runner_conda_deps, pypi_dependencies=runner_pypi_deps)  # type: ignore[call-arg]

        # 5. Build feature.test (dependencies + tasks)
        test_dependencies: dict[str, NamelessMatchSpec] = {
            "pandas": NamelessMatchSpec.from_match_spec(MatchSpec("conda-forge::pandas *")),
            "pyarrow": NamelessMatchSpec.from_match_spec(MatchSpec("conda-forge::pyarrow *")),
            "pytest": NamelessMatchSpec.from_match_spec(MatchSpec("conda-forge::pytest *")),
            "pytest-asyncio": NamelessMatchSpec.from_match_spec(
                MatchSpec("conda-forge::pytest-asyncio *")
            ),
            "pytest-check": NamelessMatchSpec.from_match_spec(
                MatchSpec("conda-forge::pytest-check *")
            ),
            "pillow": NamelessMatchSpec.from_match_spec(MatchSpec("conda-forge::pillow *")),
            "scikit-image": NamelessMatchSpec.from_match_spec(
                MatchSpec("conda-forge::scikit-image *")
            ),
            "syrupy": NamelessMatchSpec.from_match_spec(MatchSpec("conda-forge::syrupy *")),
            "playwright": NamelessMatchSpec.from_match_spec(
                MatchSpec("microsoft::playwright >=1.52.0")
            ),
        }

        test_tasks: dict[str, str | dict[str, str | list[str]]] = {
            "test-all": "python -m pytest -v tests",
            "playwright-install": "playwright install --with-deps chromium",
            "test-app-metadata": {"cmd": "python -m pytest -v tests/test_metadata.py"},
            "test-app-async-mock-io": {
                "cmd": "python -m pytest -v tests/test_results.py -k 'app and async and mock-io'",
                "depends-on": ["playwright-install"],
            },
            "test-app-sequential-mock-io": {
                "cmd": (
                    "python -m pytest -v tests/test_results.py -k 'app and sequential and mock-io'"
                ),
                "depends-on": ["playwright-install"],
            },
            "test-cli-async-mock-io": {
                "cmd": "python -m pytest -v tests/test_results.py -k 'cli and async and mock-io'",
                "depends-on": ["playwright-install"],
            },
            "test-cli-sequential-mock-io": {
                "cmd": (
                    "python -m pytest -v tests/test_results.py -k 'cli and sequential and mock-io'"
                ),
                "depends-on": ["playwright-install"],
            },
        }

        test_feature = Feature(dependencies=test_dependencies, tasks=test_tasks)

        # 6. Build environments
        # Note: using field names instead of aliases; pydantic's populate_by_name allows this
        environments = {
            "default": PixiEnvironment(solve_group="default"),  # type: ignore[call-arg]
            "runner": PixiEnvironment(  # type: ignore[call-arg]
                features=["runner"], solve_group="runner", no_default_feature=True
            ),
            "test": PixiEnvironment(  # type: ignore[call-arg]
                features=["runner", "test"], solve_group="test", no_default_feature=True
            ),
        }

        # 6b. Inject python conda dep for environments with only PyPI dependencies
        # When an environment has pypi deps but zero conda deps, pixi needs a
        # conda `python` package to provide the interpreter for resolution.
        python_dep = NamelessMatchSpec.from_match_spec(MatchSpec("conda-forge::python >=3.10,<4.0"))
        feature_map = {"runner": runner_feature, "test": test_feature}

        for _, env in environments.items():
            if env.no_default_feature:
                env_conda: dict[str, NamelessMatchSpec] = {}
                env_pypi: dict[str, str | dict[str, Any]] = {}
                for feat_name in env.features:
                    if feat_name in feature_map:
                        env_conda.update(feature_map[feat_name].dependencies)
                        env_pypi.update(feature_map[feat_name].pypi_dependencies)
                if env_pypi and not env_conda:
                    # Inject into first feature's conda dependencies
                    feature_map[env.features[0]].dependencies["python"] = python_dep
            else:
                # Default environment uses top-level deps
                if pypi_dependencies and not dependencies:
                    dependencies["python"] = python_dep

        # 7. Build tasks
        tasks: dict[str, str | dict[str, Any]] = {}

        # Add docker-build task
        if self.spec.requires_local_release_artifacts:
            # When local artifacts are required, copy them before building
            copy_local_artifacts = (
                "mkdir -p .tmp/ecoscope-workflows/release/artifacts/\n"
                "&& cp -r /tmp/ecoscope-workflows/release/artifacts/* "
                ".tmp/ecoscope-workflows/release/artifacts/\n"
            )
            tasks["docker-build"] = (
                f"{copy_local_artifacts}&& docker buildx build -t {self.release_name} .\n"
            )
        else:
            tasks["docker-build"] = f"docker buildx build -t {self.release_name} ."

        # Add workflow CLI task
        tasks[self.release_name] = f"python -m {self.package_name}.cli"

        # 8. Build system requirements (linux = "4.4.0" for Docker compatibility)
        system_requirements = {"linux": "4.4.0"}

        # Note: using field names instead of aliases; pydantic's populate_by_name allows this
        return PixiToml(  # type: ignore[call-arg]
            file_header=self.file_header,
            workspace=workspace,
            system_requirements=system_requirements,
            dependencies=dependencies,
            pypi_dependencies=pypi_dependencies,
            feature={"runner": runner_feature, "test": test_feature},
            environments=environments,
            tasks=tasks,
        )

    @property
    def release_name(self) -> str:
        """Get release directory name."""
        return f"{self.pkg_name_prefix}-{self.spec.id.replace('_', '-')}-workflow"

    @property
    def package_name(self) -> str:
        """Get Python package name."""
        return self.release_name.replace("-", "_")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def file_header(self) -> str:
        """Get file header comment."""
        # TODO: make this configurable; for now, hardcoding to minimize diff with legacy compiler
        return "# AUTOGENERATED BY ECOSCOPE-WORKFLOWS; see fingerprint in README.md for details\n"

    @ruff_formatted
    def render_dag(self, dag_type: DagTypes, mock_io: bool = False) -> str:
        """Render a DAG Python file from template.

        Args:
            dag_type: Type of DAG (async, sequential)
            mock_io: Whether to use mock I/O

        Returns:
            Formatted Python code for the DAG
        """
        loader = FileSystemLoader(self.jinja_templates_dir / "pkg" / "dags")
        env = Environment(loader=loader)
        template = env.get_template(f"run_{dag_type}.jinja2")
        testing = True if mock_io else False
        return template.render(
            self.get_dag_config(dag_type, mock_io=mock_io) | {"testing": testing}
        )

    @ruff_formatted
    def generate_params_model(self, params_jsonschema: dict[str, Any], file_header: str) -> str:
        """Generate Pydantic model from parameters JSON schema.

        Uses datamodel-code-generator to create a Pydantic V2 BaseModel
        from the JSON schema.

        Args:
            params_jsonschema: JSON schema for parameters
            file_header: File header comment

        Returns:
            Formatted Python code for Pydantic model

        Examples:
            >>> compiler = DagCompiler(spec=Spec(...))  # doctest: +SKIP
            >>> schema = {"properties": {"x": {"type": "integer"}}}  # doctest: +SKIP
            >>> model = compiler.generate_params_model(schema, "# Header")  # doctest: +SKIP
            >>> "class" in model  # doctest: +SKIP
            True
        """
        import datamodel_code_generator as dcg  # noqa: PLC0415  # deferred: heavy import (drags in black, jinja2 templates) only needed during model generation
        import datamodel_code_generator.format as dcg_format  # noqa: PLC0415  # deferred: see above

        with tempfile.NamedTemporaryFile(suffix=".py", mode="w+", delete=False) as tmp:
            output = Path(tmp.name)
            try:
                dcg.generate(
                    json.dumps(params_jsonschema),
                    input_file_type=dcg.InputFileType.JsonSchema,
                    output=output,
                    output_model_type=dcg.DataModelType.PydanticV2BaseModel,
                    output_datetime_class=dcg_format.DatetimeClassType.Datetime,
                    use_subclass_enum=True,
                    custom_file_header=file_header,
                )
                model: str = output.read_text()
            finally:
                output.unlink()  # Clean up temp file
        return model

    @ruff_formatted
    def ruffrender(self, template: str, **kws: Any) -> str:
        """Render a template and format with ruff.

        Args:
            template: Template file name
            **kws: Template variables

        Returns:
            Formatted rendered template
        """
        env = Environment(
            loader=FileSystemLoader(self.jinja_templates_dir),
            keep_trailing_newline=True,
        )
        tmpl = env.get_template(template)
        return tmpl.render(file_header=self.file_header, **kws)

    def plainrender(self, template: str, **kws: Any) -> str:
        """Render a template without formatting.

        Args:
            template: Template file name
            **kws: Template variables

        Returns:
            Rendered template (unformatted)
        """
        env = Environment(
            loader=FileSystemLoader(self.jinja_templates_dir),
            keep_trailing_newline=True,
        )
        tmpl = env.get_template(template)
        return tmpl.render(file_header=self.file_header, **kws)

    def build_pydot_graph(self) -> dot.Dot:
        """Build a pydot graph showing workflow task dependencies.

        Creates a directed graph with nodes for each task and edges
        showing data flow between tasks.

        Returns:
            pydot.Dot graph object

        Examples:
            >>> compiler = DagCompiler(spec=Spec(...))  # doctest: +SKIP
            >>> graph = compiler.build_pydot_graph()  # doctest: +SKIP
            >>> graph.get_name()  # doctest: +SKIP
            'my_workflow'
        """
        graph = dot.Dot(self.spec.id, graph_type="graph", rankdir="LR")

        # Add nodes for each task
        for t in self.spec.flat_workflow:
            # Create HTML-like label with table showing task ID, args, and return
            label = (
                "<<table border='1' cellspacing='0'>"
                f"<tr><td port='{t.id}' border='1' bgcolor='grey'>{t.id}</td></tr>"
            )
            # Add input arguments
            for arg in t.all_dependencies_dict:
                label += f"<tr><td port='{arg}' border='1'>{arg}</td></tr>"
            # Add return port
            label += "<tr><td port='return' border='1'><i>return</i></td></tr></table>>"
            node = dot.Node(t.id, shape="none", label=label)
            graph.add_node(node)

        # Add edges for dependencies
        for t in self.spec.flat_workflow:
            for arg, dep_list in t.all_dependencies_dict.items():
                for dep_id in dep_list:
                    edge = dot.Edge(
                        f"{dep_id}:return",
                        f"{t.id}:{arg}",
                        dir="forward",
                        arrowhead="normal",
                    )
                    graph.add_edge(edge)

        return graph

    def compile(
        self,
        spec_relpath: str,
        installed_requirements: list[SpecRequirement] | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> WorkflowArtifacts:
        """Compile the workflow spec into complete artifacts.

        This is the main entry point for compilation.

        Args:
            spec_relpath: Relative path to the spec file
            installed_requirements: Optional list of solved/pinned requirements
            on_progress: Optional callback invoked with a status message at each sub-step

        Returns:
            WorkflowArtifacts with all generated files

        Examples:
            >>> from wt_compiler.spec import Spec
            >>> # spec = Spec(...)  # doctest: +SKIP
            >>> # compiler = DagCompiler(spec=spec)  # doctest: +SKIP
            >>> # artifacts = compiler.compile("path/to/spec.yaml")  # doctest: +SKIP
        """
        if on_progress is not None:
            on_progress("Generating schemas...")
        # Generate parameter schemas (both flat and hierarchical)
        params_schema_flat = self.get_params_jsonschema(flat=True)
        params_schema_hierarchical = self.get_params_jsonschema(flat=False)

        # Apply RJSF overrides only to hierarchical schema (rjsf.json),
        # not to flat schema (params.json), matching legacy behavior.
        if self.spec.rjsf_overrides:
            params_schema_hierarchical = self.spec.rjsf_overrides.apply_overrides(
                params_schema_hierarchical
            )

        # Create titled versions for model generation
        params_mod = params_schema_flat.model_copy(update={"title": "Params"})
        formdata_mod = params_schema_hierarchical.model_copy(update={"title": "FormData"})

        def _mdump(j: Any) -> dict[str, Any]:
            result: dict[str, Any] = j.model_dump(by_alias=True, exclude_none=True)
            return result

        if on_progress is not None:
            on_progress("Rendering DAGs...")
        # Generate DAGs
        dags = Dags(
            **{
                "__init__.py": self.ruffrender("pkg/dags/init.jinja2"),
                "run_sequential_mock_io.py": self.render_dag("sequential", mock_io=True),
                "run_sequential.py": self.render_dag("sequential", mock_io=False),
            }
        )

        if on_progress is not None:
            on_progress("Generating package files...")
        # Generate package files
        package = PackageDirectory(
            dags=dags,
            **{  # type: ignore[arg-type]
                "rjsf.json": _mdump(params_schema_hierarchical),
                "params.json": _mdump(params_schema_flat),
                "params.py": self.generate_params_model(_mdump(params_mod), self.file_header),
                "formdata.py": self.generate_params_model(_mdump(formdata_mod), self.file_header),
                "cli.py": self.ruffrender(
                    "pkg/cli.jinja2",
                    release_name=self.release_name,
                    results_env_var=self.results_env_var,
                ),
                "dispatch.py": self.ruffrender("pkg/dispatch.jinja2"),
                "metadata.py": self.ruffrender("pkg/metadata.jinja2"),
                "response.py": self.ruffrender("pkg/response.jinja2"),
                "__init__.py": "",
            },
        )

        if on_progress is not None:
            on_progress("Generating tests...")
        # Generate tests
        tests = Tests(
            **{
                "conftest.py": self.ruffrender(
                    "tests/conftest.jinja2",
                    package_name=self.package_name,
                    release_name=self.release_name,
                    results_env_var=self.results_env_var,
                    io_tasks_importable_references=[
                        t.known_task.importable_reference
                        for t in self.spec.flat_workflow
                        if TaskTag.io in t.known_task.tags
                    ],
                ),
                "test_metadata.py": self.ruffrender(
                    "tests/test_metadata.jinja2",
                    package_name=self.package_name,
                ),
                "test_results.py": self.ruffrender("tests/test_results.jinja2"),
            }
        )

        # Generate pixi.toml
        pixi_toml = self.get_pixi_toml()

        # Generate Dockerfile
        dockerfile = self.plainrender(
            "Dockerfile.jinja2",
            pixi_version=os.environ.get("PIXI_VERSION", "latest"),
            requires_local_release_artifacts=self.spec.requires_local_release_artifacts,
            release_name=self.release_name,
            results_env_var=self.results_env_var,
        )

        # Generate .dockerignore
        dockerignore = self.plainrender("dockerignore.jinja2")

        if on_progress is not None:
            on_progress("Building graph...")
        # Generate pydot graph
        pydot_graph = self.build_pydot_graph()

        # Create WorkflowArtifacts (without README yet - need fingerprint)
        artifacts = WorkflowArtifacts(
            spec_relpath=spec_relpath,
            release_name=self.release_name,
            package_name=self.package_name,
            package=package,
            tests=tests,
            **{  # type: ignore[arg-type]
                "pixi.toml": pixi_toml,
                "graph.png": pydot_graph,
                "Dockerfile": dockerfile,
                ".dockerignore": dockerignore,
            },
        )

        # Generate README with fingerprint
        fingerprint = Fingerprint(
            spec=self.spec,
            wa=artifacts,
            installed_requirements=installed_requirements or [],
        )
        readme_md = self.plainrender(
            "README.jinja2",
            fingerprint=fingerprint.to_yaml(),
            spec_id=self.spec.id,
            release_name=self.release_name,
        )
        artifacts.readme_md = readme_md

        return artifacts


def compile_workflow(
    spec: Spec,
    spec_relpath: str,
    wt_runner_channel: str | None = None,
    wt_pypi_deps: dict[str, str | dict[str, Any]] | None = None,
    installed_requirements: list[SpecRequirement] | None = None,
    on_progress: Callable[[str], None] | None = None,
    **compiler_kwargs: Any,
) -> WorkflowArtifacts:
    """Compile a workflow from a validated Spec.

    Note: If calling with a Spec directly, ensure the global known_tasks dict
    is populated first via discovery. For automatic discovery, use
    compile_workflow_from_yaml() instead.

    Args:
        spec: Workflow specification (must have known_tasks already populated)
        spec_relpath: Relative path to spec file
        wt_runner_channel: Channel URL where wt-runner package is available.
            Can be None when wt_pypi_deps is set (PyPI mode).
        wt_pypi_deps: Optional dict mapping sibling package names to pixi
            pypi-dependency values. When set, wt-runner/wt-task are installed
            from PyPI instead of conda.
        installed_requirements: Optional list of solved/pinned requirements
        on_progress: Optional callback invoked with a status message at each sub-step
        **compiler_kwargs: Additional arguments for DagCompiler

    Returns:
        Compiled workflow artifacts

    Examples:
        >>> from wt_compiler.spec import Spec
        >>> # For manual workflow (requires known_tasks to be populated):
        >>> # spec = Spec.model_validate(data)  # doctest: +SKIP
        >>> # artifacts = compile_workflow(  # doctest: +SKIP
        ... #     spec, "spec.yaml", wt_runner_channel="...",
        ... # )
        >>>
        >>> # Prefer using compile_workflow_from_yaml() for automatic discovery:
        >>> # artifacts = compile_workflow_from_yaml("spec.yaml")  # doctest: +SKIP
    """
    compiler = DagCompiler(
        spec=spec,
        wt_runner_channel=wt_runner_channel,
        wt_pypi_deps=wt_pypi_deps,
        **compiler_kwargs,
    )
    return compiler.compile(
        spec_relpath, installed_requirements=installed_requirements, on_progress=on_progress
    )


class ParsedRequirements(NamedTuple):
    """Result of parsing requirements from a spec YAML.

    Separates conda (SpecRequirement) and pypi (PyPIRequirement) dependencies.
    """

    conda: list[SpecRequirement]
    pypi: list[PyPIRequirement]


def _parse_requirements_from_yaml(yaml_path: Path) -> ParsedRequirements:
    """Parse just the requirements from a spec YAML without full Spec validation.

    This enables task discovery before full Spec validation, since Spec validation
    requires the global known_tasks dict to be populated.

    Args:
        yaml_path: Path to the spec.yaml file

    Returns:
        ParsedRequirements with separate conda and pypi lists

    Raises:
        FileNotFoundError: If yaml_path doesn't exist
        ValueError: If requirements section is missing or invalid
    """
    with open(yaml_path) as f:
        data = yaml.load(f)

    if "requirements" not in data:
        raise ValueError(
            f"Spec file {yaml_path} is missing 'requirements' section. "
            "Requirements are needed to discover tasks."
        )

    # Parse only requirements - minimal validation
    conda_requirements: list[SpecRequirement] = []
    pypi_requirements: list[PyPIRequirement] = []
    for req_data in data["requirements"]:
        if _conda_or_pypi(req_data) == "pypi":
            pypi_requirements.append(PyPIRequirement.model_validate(req_data))
        else:
            conda_requirements.append(SpecRequirement.model_validate(req_data))

    return ParsedRequirements(conda=conda_requirements, pypi=pypi_requirements)


async def compile_workflow_from_yaml(
    yaml_path: str | Path,
    progress: bool = True,
    **compiler_kwargs: Any,
) -> WorkflowArtifacts:
    """Compile a workflow from a spec.yaml file with automatic task discovery.

    This async function is the recommended entry point for compilation. It handles
    the complete workflow:
    1. Parse requirements from YAML (without full Spec validation)
    2. Discover tasks via wt-registry CLI in ephemeral rattler environment
    3. Validate full Spec (now works because known_tasks is populated)
    4. Compile to workflow artifacts

    Args:
        yaml_path: Path to spec.yaml file
        progress: Whether to display a progress spinner on stderr (default: True).
            Automatically disabled when stderr is not a TTY.
        **compiler_kwargs: Additional arguments for DagCompiler

    Returns:
        Compiled workflow artifacts

    Raises:
        FileNotFoundError: If yaml_path doesn't exist
        ValueError: If spec is invalid
        subprocess.CalledProcessError: If wt-registry CLI fails

    Examples:
        >>> # Compile a workflow with automatic discovery:
        >>> # artifacts = await compile_workflow_from_yaml("spec.yaml")  # doctest: +SKIP
        >>> # artifacts.dump("output/")  # doctest: +SKIP
    """
    yaml_path = Path(yaml_path)

    with spinner(progress) as sp:
        # Phase 1: Parse requirements from YAML
        sp.update("Parsing requirements...")
        parsed_reqs = _parse_requirements_from_yaml(yaml_path)
        conda_requirements = parsed_reqs.conda
        pypi_requirements = parsed_reqs.pypi

        # Phase 2: Convert SpecRequirements to MatchSpecs and discover tasks
        # Build MatchSpec strings: "{channel}::{name} {version}"
        # Use base_url (not name) to ensure custom channels are correctly identified
        # Also collect channels to pass to the discovery function
        match_specs = []
        channels = []
        for req in conda_requirements:
            # Use base_url for the matchspec to correctly identify custom channels
            # (using just the name would default to conda.anaconda.org)
            channel_str = req.channel.base_url
            channels.append(req.channel)
            version_str = str(req.version.version) if req.version.version else ""
            matchspec_str = f"{channel_str}::{req.name} {version_str}".strip()
            match_specs.append(MatchSpec(matchspec_str))

        # Deduplicate channels while preserving order, keyed by base_url
        unique_channels = list({c.base_url: c for c in channels}.values())

        if conda_requirements:
            # Add all known channels for transitive dependency resolution
            # (only needed when there are conda requirements from custom channels)
            for known_channel in CHANNELS:
                if not any(c.base_url == known_channel.base_url for c in unique_channels):
                    unique_channels.append(known_channel)

            # Filter out file:// channels that don't exist on the local filesystem
            def _local_channel_exists(channel: "Channel") -> bool:
                base_url = channel.base_url
                if base_url.startswith("file://"):
                    local_path = Path(base_url.replace("file://", ""))
                    return local_path.exists()
                return True  # Non-local channels are always "valid"

            unique_channels = [c for c in unique_channels if _local_channel_exists(c)]
        else:
            # PyPI-only: just need conda-forge for python + uv
            unique_channels = [CONDA_FORGE_CHANNEL]

        # Discover tasks and populate global known_tasks
        discovery_result = await populate_known_tasks(
            match_specs,
            channels=unique_channels,
            pypi_requirements=pypi_requirements or None,
            on_progress=sp.update,
        )
        records = discovery_result.records

        # Extract wt-runner channel from the solved wt-registry record
        wt_registry_record = next(
            (r for r in records if str(r.name.normalized) == "wt-registry"), None
        )
        if wt_registry_record is not None:
            wt_runner_channel: str | None = str(wt_registry_record.channel)
            wt_pypi_deps = None
        else:
            wt_runner_channel = None
            wt_pypi_deps = discovery_result.wt_pypi_deps

        # Build installed requirements from solved records
        installed_requirements = _build_installed_requirements(conda_requirements, records)

        # Phase 3: Now we can safely validate the full Spec
        sp.update("Validating spec...")
        with open(yaml_path) as f:
            data = yaml.load(f)
        spec = Spec.model_validate(data)

        # Phase 4: Compile
        sp.update("Compiling artifacts...")
        spec_relpath = str(yaml_path)
        return compile_workflow(
            spec,
            spec_relpath,
            wt_runner_channel=wt_runner_channel,
            wt_pypi_deps=wt_pypi_deps,
            installed_requirements=installed_requirements,
            on_progress=sp.update,
            **compiler_kwargs,
        )
