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
import pathlib
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    pass
else:
    pass

import pydot as dot
import ruamel.yaml
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, computed_field
from rattler import Channel

from wt_compiler.artifacts import (
    Dags,
    PackageDirectory,
    PixiToml,
    PixiWorkspace,
    Tests,
    WorkflowArtifacts,
)
from wt_compiler.discovery import populate_known_tasks
from wt_compiler.formatting import ruff_formatted
from wt_compiler.jsonschema import ReactJSONSchemaFormConfiguration, find_referenced_defs
from wt_compiler.spec import (
    DagTypes,
    KnownTaskArgName,
    Spec,
    SpecRequirement,
    TaskInstance,
    TaskInstanceId,
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


class Fingerprint(BaseModel):
    """A fingerprint of the spec and its artifacts.

    Used for version management and change detection.
    """

    spec: Spec
    wa: WorkflowArtifacts

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
    jinja_templates_dir: pathlib.Path = TEMPLATES
    pkg_name_prefix: str = "wt"

    def get_dag_config(self, dag_type: DagTypes, mock_io: bool) -> dict[str, Any]:
        """Get configuration dict for rendering a DAG.

        Args:
            dag_type: Type of DAG to generate (jupytext, async, sequential)
            mock_io: Whether to use mock I/O for testing

        Returns:
            Configuration dictionary for template rendering
        """
        dag_config = self.model_dump(
            exclude={"jinja_templates_dir"},
            context={"mock_io": mock_io},
        )
        if dag_type == "jupytext":
            dag_config |= {
                "per_taskinstance_params_notebook": self.get_per_taskinstance_params_notebook(),
            }
        return dag_config

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
        from wt_compiler.spec import TaskGroup

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

        # Apply RJSF overrides from spec
        if self.spec.rjsf_overrides:
            config = self.spec.rjsf_overrides.apply_overrides(config)

        return config

    def get_params_fillable_yaml(self) -> str:
        """Generate a fillable YAML template for parameters.

        Returns:
            YAML string with placeholder values
        """
        # TODO: Implement based on params schema
        return "# TODO: Generate fillable params YAML\n"

    def get_per_taskinstance_params_notebook(self) -> dict[str, str]:
        """Generate per-task parameter notebooks for jupytext DAG.

        Creates a dict mapping task IDs to parameter dict code strings
        for use in Jupyter notebooks.

        Returns:
            Mapping of task ID to notebook content

        Examples:
            >>> compiler = DagCompiler(spec=Spec(...))  # doctest: +SKIP
            >>> notebooks = compiler.get_per_taskinstance_params_notebook()  # doctest: +SKIP
            >>> "task1" in notebooks  # doctest: +SKIP
            True
        """
        return {
            t.id: t.known_task.parameters_notebook(
                omit_args=self.per_taskinstance_omit_args.get(t.id, [])
            )
            for t in self.spec.flat_workflow
        }

    def get_pixi_toml(self) -> PixiToml:
        """Generate pixi.toml for the workflow.

        Returns:
            PixiToml model with all dependencies and configuration
        """
        dependencies = {req.name: req.version for req in self.spec.requirements}

        pixi_toml = PixiToml(
            file_header=self.file_header,
            workspace=PixiWorkspace(name=self.package_name),
            dependencies=dependencies,
        )

        return pixi_toml

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
            dag_type: Type of DAG (jupytext, async, sequential)
            mock_io: Whether to use mock I/O

        Returns:
            Formatted Python code for the DAG
        """
        loader = FileSystemLoader(self.jinja_templates_dir / "pkg" / "dags")
        env = Environment(loader=loader)
        template = env.get_template(
            f"run_{dag_type}.jinja2" if dag_type != "jupytext" else "jupytext.jinja2"
        )
        testing = True if mock_io else False
        return template.render(
            self.get_dag_config(dag_type, mock_io=mock_io) | {"testing": testing}
        )

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
        import tempfile

        import datamodel_code_generator as dcg
        import datamodel_code_generator.format as dcg_format

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

    def compile(self, spec_relpath: str) -> WorkflowArtifacts:
        """Compile the workflow spec into complete artifacts.

        This is the main entry point for compilation.

        Args:
            spec_relpath: Relative path to the spec file

        Returns:
            WorkflowArtifacts with all generated files

        Examples:
            >>> from wt_compiler.spec import Spec
            >>> # spec = Spec(...)  # doctest: +SKIP
            >>> # compiler = DagCompiler(spec=spec)  # doctest: +SKIP
            >>> # artifacts = compiler.compile("path/to/spec.yaml")  # doctest: +SKIP
        """
        # Generate parameter schemas (both flat and hierarchical)
        params_schema_flat = self.get_params_jsonschema(flat=True)
        params_schema_hierarchical = self.get_params_jsonschema(flat=False)

        # Create titled versions for model generation
        params_mod = params_schema_flat.model_copy(update={"title": "Params"})
        formdata_mod = params_schema_hierarchical.model_copy(update={"title": "FormData"})

        def _mdump(j: Any) -> dict[str, Any]:
            result: dict[str, Any] = j.model_dump(by_alias=True, exclude_none=True)
            return result

        # Generate DAGs
        dags = Dags(
            **{
                "__init__.py": self.ruffrender("pkg/dags/init.jinja2"),
                "jupytext.py": self.render_dag("jupytext", mock_io=False),
                "run_async_mock_io.py": self.render_dag("async", mock_io=True),
                "run_async.py": self.render_dag("async", mock_io=False),
                "run_sequential_mock_io.py": self.render_dag("sequential", mock_io=True),
                "run_sequential.py": self.render_dag("sequential", mock_io=False),
            }
        )

        # Generate package files
        package = PackageDirectory(
            dags=dags,
            **{  # type: ignore[arg-type]
                "rjsf.json": _mdump(params_schema_hierarchical),
                "params.json": _mdump(params_schema_flat),
                "params.py": self.generate_params_model(_mdump(params_mod), self.file_header),
                "formdata.py": self.generate_params_model(_mdump(formdata_mod), self.file_header),
                "cli.py": self.ruffrender("pkg/cli.jinja2", release_name=self.release_name),
                "dispatch.py": self.ruffrender("pkg/dispatch.jinja2"),
                "metadata.py": self.ruffrender("pkg/metadata.jinja2"),
                "response.py": self.ruffrender("pkg/response.jinja2"),
                "__init__.py": "",
            },
        )

        # Generate tests
        from wt_compiler.spec import TaskTag

        tests = Tests(
            **{
                "conftest.py": self.ruffrender(
                    "tests/conftest.jinja2",
                    package_name=self.package_name,
                    release_name=self.release_name,
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
        dockerfile = self.plainrender("Dockerfile.jinja2")

        # Generate .dockerignore
        dockerignore = self.plainrender("dockerignore.jinja2")

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
        fingerprint = Fingerprint(spec=self.spec, wa=artifacts)
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
    **compiler_kwargs: Any,
) -> WorkflowArtifacts:
    """Compile a workflow from a validated Spec.

    Note: If calling with a Spec directly, ensure the global known_tasks dict
    is populated first via discovery. For automatic discovery, use
    compile_workflow_from_yaml() instead.

    Args:
        spec: Workflow specification (must have known_tasks already populated)
        spec_relpath: Relative path to spec file
        **compiler_kwargs: Additional arguments for DagCompiler

    Returns:
        Compiled workflow artifacts

    Examples:
        >>> from wt_compiler.spec import Spec
        >>> # For manual workflow (requires known_tasks to be populated):
        >>> # spec = Spec.model_validate(data)  # doctest: +SKIP
        >>> # artifacts = compile_workflow(spec, "spec.yaml")  # doctest: +SKIP
        >>>
        >>> # Prefer using compile_workflow_from_yaml() for automatic discovery:
        >>> # artifacts = compile_workflow_from_yaml("spec.yaml")  # doctest: +SKIP
    """
    compiler = DagCompiler(spec=spec, **compiler_kwargs)
    return compiler.compile(spec_relpath)


def _parse_requirements_from_yaml(yaml_path: Path) -> list[SpecRequirement]:
    """Parse just the requirements from a spec YAML without full Spec validation.

    This enables task discovery before full Spec validation, since Spec validation
    requires the global known_tasks dict to be populated.

    Args:
        yaml_path: Path to the spec.yaml file

    Returns:
        List of SpecRequirement objects

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
    requirements = []
    for req_data in data["requirements"]:
        requirements.append(SpecRequirement.model_validate(req_data))

    return requirements


async def compile_workflow_from_yaml(
    yaml_path: str | Path,
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
    from rattler import MatchSpec

    yaml_path = Path(yaml_path)

    # Phase 1: Parse requirements from YAML
    requirements = _parse_requirements_from_yaml(yaml_path)

    # Phase 2: Convert SpecRequirements to MatchSpecs and discover tasks
    # Build MatchSpec strings: "{channel}::{name} {version}"
    # Use base_url (not name) to ensure custom channels are correctly identified
    # Also collect channels to pass to the discovery function
    match_specs = []
    channels = []
    for req in requirements:
        # Use base_url for the matchspec to correctly identify custom channels
        # (using just the name would default to conda.anaconda.org)
        channel_str = req.channel.base_url
        channels.append(req.channel)
        version_str = str(req.version.version) if req.version.version else ""
        matchspec_str = f"{channel_str}::{req.name} {version_str}".strip()
        match_specs.append(MatchSpec(matchspec_str))

    # Deduplicate channels while preserving order, keyed by base_url
    unique_channels = list({c.base_url: c for c in channels}.values())

    # Add all known channels for transitive dependency resolution
    # This uses CHANNELS from requirements.py as the single source of truth
    from wt_compiler.requirements import CHANNELS

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

    # Discover tasks and populate global known_tasks
    await populate_known_tasks(match_specs, channels=unique_channels)

    # Phase 3: Now we can safely validate the full Spec
    with open(yaml_path) as f:
        data = yaml.load(f)
    spec = Spec.model_validate(data)

    # Phase 4: Compile
    spec_relpath = str(yaml_path)
    return compile_workflow(spec, spec_relpath, **compiler_kwargs)
