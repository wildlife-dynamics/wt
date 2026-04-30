"""Artifact generation models for workflow compilation."""

import copy
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pydot as dot
import ruamel.yaml
import tomli_w
from pydantic import BaseModel, ConfigDict, Field

from wt_compiler._models import (
    _AllowArbitraryAndValidateAssignment,
    _AllowArbitraryTypes,
)
from wt_compiler.requirements import (
    CHANNELS,
    PLATFORMS,
    ChannelType,
    NamelessMatchSpecType,
    PlatformType,
)

yaml = ruamel.yaml.YAML(typ="safe")


class Dags(BaseModel):
    """Target directory for the generated DAGs."""

    init_dot_py: str = Field(..., alias="__init__.py")
    run_sequential_mock_io: str = Field(..., alias="run_sequential_mock_io.py")
    run_sequential: str = Field(..., alias="run_sequential.py")


class PixiWorkspace(_AllowArbitraryTypes):
    """Pixi workspace configuration."""

    name: str
    # mypy throws:
    # `error: List comprehension has incompatible type List[str | None];
    #  expected List[Channel]  [misc]`
    # `error: List comprehension has incompatible type List[str];
    #  expected List[Platform]  [misc]`
    # but pydantic parsing handles these correctly
    # (and stumbles without the list comprehension)
    channels: list[ChannelType] = [c.name for c in CHANNELS]  # type: ignore[misc]
    platforms: list[PlatformType] = [str(p) for p in PLATFORMS]  # type: ignore[misc]


FeatureName = str
PixiTaskName = str
# A pixi task can be a simple string command, or a dict with cmd, env, depends_on, etc.
PixiTaskCommand = str | dict[str, Any]


class Feature(_AllowArbitraryTypes):
    """A `pixi.toml` feature definition."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        populate_by_name=True,
    )

    dependencies: dict[str, NamelessMatchSpecType]
    pypi_dependencies: dict[str, str | dict[str, Any]] = Field(
        default_factory=dict, alias="pypi-dependencies"
    )
    tasks: dict[PixiTaskName, PixiTaskCommand] = Field(default_factory=dict)


class Environment(BaseModel):
    """Pixi environment configuration."""

    model_config = ConfigDict(populate_by_name=True)

    features: list[FeatureName] = Field(default_factory=list)
    solve_group: str = Field(default="default", alias="solve-group")
    no_default_feature: bool = Field(default=False, alias="no-default-feature")


class PixiToml(_AllowArbitraryAndValidateAssignment):
    """The pixi.toml file that specifies the workflow.

    This model represents the complete pixi configuration including workspace,
    dependencies, features, environments, and tasks.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
        populate_by_name=True,
    )

    workspace: PixiWorkspace
    system_requirements: dict[str, str] = Field(default_factory=dict, alias="system-requirements")
    dependencies: dict[str, NamelessMatchSpecType]
    pypi_dependencies: dict[str, str | dict[str, Any]] = Field(
        default_factory=dict, alias="pypi-dependencies"
    )
    feature: dict[FeatureName, Feature] = Field(default_factory=dict)
    environments: dict[str, Environment] = Field(default_factory=dict)
    tasks: dict[PixiTaskName, PixiTaskCommand] = Field(default_factory=dict)
    file_header: str = Field(default="", exclude=True)

    @classmethod
    def from_file(cls, src: str | Path) -> "PixiToml":
        """Load a PixiToml from a file.

        Args:
            src: Path to the pixi.toml file

        Returns:
            A PixiToml instance

        Examples:
            >>> from pathlib import Path
            >>> # pixi = PixiToml.from_file("path/to/pixi.toml")  # doctest: +SKIP
        """
        if isinstance(src, str):
            src = Path(src)
        with src.open("rb") as f:
            content = tomllib.load(f)
        return cls(**content)

    @classmethod
    def from_text(cls, text: str) -> "PixiToml":
        """Load a PixiToml from a text string.

        Args:
            text: TOML text content

        Returns:
            A PixiToml instance

        Examples:
            >>> toml_text = '''
            ... [workspace]
            ... name = "my-workflow"
            ... channels = ["conda-forge"]
            ... platforms = ["linux-64"]
            ...
            ... [dependencies]
            ... python = ">=3.10"
            ... '''
            >>> pixi = PixiToml.from_text(toml_text)  # doctest: +SKIP
        """
        return cls(**tomllib.loads(text))

    def add_dependency(self, name: str, version: str, channel: str | None = None) -> None:
        """Add a dependency to the `dependencies` section.

        Args:
            name: Package name
            version: Version specification
            channel: Optional channel specification

        Examples:
            >>> pixi = PixiToml(
            ...     workspace=PixiWorkspace(name="test"),
            ...     dependencies={}
            ... )
            >>> pixi.add_dependency("numpy", ">=1.20.0")  # doctest: +SKIP
            >>> pixi.add_dependency("custom-pkg", ">=0.1.0", "mychannel")  # doctest: +SKIP
        """
        deps_copy = copy.deepcopy(self.model_dump()["dependencies"])
        deps_copy[name] = {"version": version} | ({"channel": channel} if channel else {})
        # we do not get assignment validation/parsing
        # unless we re-assign .dependencies, so do that
        self.dependencies = deps_copy

    def _model_dump_for_toml(self) -> dict[str, Any]:
        """Dump model to dict for TOML serialization, excluding empty pypi-dependencies."""
        data = self.model_dump(by_alias=True, mode="json")
        if not data.get("pypi-dependencies"):
            data.pop("pypi-dependencies", None)
        # Also strip empty pypi-dependencies from feature dicts
        for feature_data in data.get("feature", {}).values():
            if not feature_data.get("pypi-dependencies"):
                feature_data.pop("pypi-dependencies", None)
        return data

    def dump(self, dst: Path) -> None:
        """Write the PixiToml to a file.

        Args:
            dst: Destination path for the pixi.toml file

        Examples:
            >>> from pathlib import Path
            >>> pixi = PixiToml(
            ...     workspace=PixiWorkspace(name="test"),
            ...     dependencies={}
            ... )
            >>> # pixi.dump(Path("pixi.toml"))  # doctest: +SKIP
        """
        with dst.open("wb") as f:
            f.write(self.file_header.encode("utf-8"))
            f.write(b"\n")
            tomli_w.dump(self._model_dump_for_toml(), f)

    def to_toml(self) -> str:
        """Serialize to TOML string.

        Returns:
            TOML-formatted string representation

        Examples:
            >>> pixi = PixiToml(
            ...     workspace=PixiWorkspace(name="test"),
            ...     dependencies={"python": ">=3.10"}
            ... )
            >>> toml_str = pixi.to_toml()  # doctest: +SKIP
            >>> "test" in toml_str  # doctest: +SKIP
            True
        """
        import io

        buffer = io.BytesIO()
        if self.file_header:
            buffer.write(self.file_header.encode("utf-8"))
            buffer.write(b"\n")
        tomli_w.dump(self._model_dump_for_toml(), buffer)
        return buffer.getvalue().decode("utf-8")


class Tests(BaseModel):
    """Test artifacts for the workflow."""

    conftest: str = Field(..., alias="conftest.py")
    test_metadata: str = Field(..., alias="test_metadata.py")
    test_results: str = Field(..., alias="test_results.py")

    def dump(self, dst: Path) -> None:
        """Write test files to the tests directory.

        Args:
            dst: Destination directory (will create tests/ subdirectory)

        Examples:
            >>> from pathlib import Path
            >>> tests = Tests(
            ...     **{
            ...         "conftest.py": "# conftest",
            ...         "test_metadata.py": "# test metadata",
            ...         "test_results.py": "# test results"
            ...     }
            ... )
            >>> # tests.dump(Path("output"))  # doctest: +SKIP
        """
        dst.joinpath("tests").mkdir(parents=True)
        for fname, content in self.model_dump(by_alias=True).items():
            dst.joinpath("tests").joinpath(fname).write_text(content)


class PackageDirectory(BaseModel):
    """Package directory structure for the workflow."""

    dags: Dags
    rjsf: dict[str, Any] = Field(..., alias="rjsf.json")
    params_json: dict[str, Any] = Field(..., alias="params.json")
    cli: str = Field(..., alias="cli.py")
    dispatch: str = Field(..., alias="dispatch.py")
    metadata: str = Field(..., alias="metadata.py")
    response: str = Field(..., alias="response.py")
    init_dot_py: str = Field(default="", alias="__init__.py")

    def dump(self, dst: Path) -> None:
        """Write package files to the package directory.

        Args:
            dst: Destination directory for the package

        Examples:
            >>> from pathlib import Path
            >>> # pkg = PackageDirectory(...)  # doctest: +SKIP
            >>> # pkg.dump(Path("my_workflow"))  # doctest: +SKIP
        """
        for fname, content in self.model_dump(
            by_alias=True, exclude={"rjsf", "dags", "params_json"}
        ).items():
            dst.joinpath(fname).write_text(content)
        with dst.joinpath("rjsf.json").open("w") as f:
            json.dump(self.rjsf, f, indent=2)
            f.write("\n")
        with dst.joinpath("params.json").open("w") as f:
            json.dump(self.params_json, f, indent=2)
            f.write("\n")
        dst.joinpath("dags").mkdir(parents=True)
        for fname, content in self.dags.model_dump(by_alias=True).items():
            dst.joinpath("dags").joinpath(fname).write_text(content)


class VersionYaml(BaseModel):
    """Version information for the workflow."""

    MAJ: int
    MIN: int
    PATCH: int = 0

    @classmethod
    def bump_from(
        cls,
        prior_version: "VersionYaml",
        prior_params_sha256: str,
        new_params_sha256: str,
    ) -> "VersionYaml":
        """Calculate new version by comparing parameter hashes.

        If params changed, bump major version. Otherwise, bump minor version.

        Args:
            prior_version: The previous version
            prior_params_sha256: SHA256 hash of previous parameters
            new_params_sha256: SHA256 hash of new parameters

        Returns:
            A new VersionYaml with bumped version

        Examples:
            >>> prior = VersionYaml(MAJ=1, MIN=2)
            >>> # Minor bump (params unchanged)
            >>> v1 = VersionYaml.bump_from(prior, "abc123", "abc123")
            >>> (v1.MAJ, v1.MIN)
            (1, 3)
            >>> # Major bump (params changed)
            >>> v2 = VersionYaml.bump_from(prior, "abc123", "def456")
            >>> (v2.MAJ, v2.MIN)
            (2, 0)
        """
        if prior_params_sha256 == new_params_sha256:
            return cls(MAJ=prior_version.MAJ, MIN=prior_version.MIN + 1)
        return cls(MAJ=prior_version.MAJ + 1, MIN=0)

    def dump(self, dst: Path) -> None:
        """Write version to YAML file.

        Args:
            dst: Destination path for VERSION.yaml

        Examples:
            >>> from pathlib import Path
            >>> v = VersionYaml(MAJ=1, MIN=2, PATCH=3)
            >>> # v.dump(Path("VERSION.yaml"))  # doctest: +SKIP
        """
        with dst.open("wb") as f:
            yaml.dump(self.model_dump(), f)


SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")


def _params_sha256_from_readme(readme_md: str) -> str:
    """Extract params_sha256 from README markdown.

    Args:
        readme_md: README markdown content

    Returns:
        SHA256 hash string

    Raises:
        AssertionError: If params_sha256 is invalid
    """
    fingerprint_text = readme_md.split("```yaml")[-1].split("```")[0]
    fingerprint_yaml: dict[str, Any] = yaml.load(fingerprint_text)
    params_sha256 = fingerprint_yaml.get("params_sha256", None)
    assert isinstance(params_sha256, str), "params_sha256 must be a string."
    assert SHA256.match(params_sha256), "params_sha256 must be a valid SHA256 hash."
    return params_sha256.strip()


class WorkflowArtifacts(_AllowArbitraryTypes):
    """Complete set of workflow artifacts.

    This is the main container for all generated workflow files including
    package code, tests, configuration, and documentation.
    """

    spec_relpath: str
    release_name: str
    package_name: str
    package: PackageDirectory
    tests: Tests
    pixi_toml: PixiToml = Field(..., alias="pixi.toml")
    dockerfile: str = Field(..., alias="Dockerfile")
    dockerignore: str = Field(..., alias=".dockerignore")
    pyproject_toml: str = Field(..., alias="pyproject.toml")
    hatch_build_py: str = Field(..., alias="hatch_build.py")
    pydot_graph: dot.Dot | None = Field(None, alias="graph.png")
    readme_md: str | None = Field(None, alias="README.md")

    @property
    def release_dir(self) -> Path:
        """Get the release directory path.

        Returns:
            Path to the release directory
        """
        return Path().cwd().joinpath(self.spec_relpath).parent.joinpath(self.release_name)

    def install(self) -> None:
        """Install dependencies using pixi."""
        subprocess.run(
            f"pixi install -a --manifest-path {self.release_dir.joinpath('pixi.toml')}".split()
        )

    def update(self) -> None:
        """Update dependencies using pixi without installing."""
        manifest_path = self.release_dir.joinpath("pixi.toml")
        subprocess.run(f"pixi update --no-install --manifest-path {manifest_path}".split())

    @classmethod
    def from_disk(cls, spec_relpath: str, artifacts_dir: str | Path) -> "WorkflowArtifacts":
        """Load workflow artifacts from disk.

        Args:
            spec_relpath: Relative path to the spec file
            artifacts_dir: Directory containing the artifacts

        Returns:
            A WorkflowArtifacts instance

        Examples:
            >>> from pathlib import Path
            >>> # artifacts = WorkflowArtifacts.from_disk("spec.yaml", "wf")  # doctest: +SKIP
        """
        if isinstance(artifacts_dir, str):
            artifacts_dir = Path(artifacts_dir)

        pixi_toml = PixiToml.from_file(artifacts_dir.joinpath("pixi.toml"))
        dockerfile = artifacts_dir.joinpath("Dockerfile").read_text()
        dockerignore = artifacts_dir.joinpath(".dockerignore").read_text()
        pyproject_toml = artifacts_dir.joinpath("pyproject.toml").read_text()
        hatch_build_py = artifacts_dir.joinpath("hatch_build.py").read_text()
        readme_md = artifacts_dir.joinpath("README.md").read_text()
        tests = Tests(**{f.name: f.read_text() for f in artifacts_dir.joinpath("tests").iterdir()})
        package_name = artifacts_dir.name.replace("-", "_")
        package = PackageDirectory(
            **{  # type: ignore[arg-type]
                f.name: (f.read_text() if not f.suffix == ".json" else json.load(f.open()))
                for f in artifacts_dir.joinpath(package_name).iterdir()
                if f.is_file()
            },
            dags=Dags(
                **{
                    f.name: f.read_text()
                    for f in artifacts_dir.joinpath(package_name, "dags").iterdir()
                }
            ),
        )
        return WorkflowArtifacts(
            spec_relpath=spec_relpath,
            release_name=artifacts_dir.name,
            package_name=package_name,
            package=package,
            tests=tests,
            **{  # type: ignore[arg-type]
                "pixi.toml": pixi_toml,
                "Dockerfile": dockerfile,
                ".dockerignore": dockerignore,
                "pyproject.toml": pyproject_toml,
                "hatch_build.py": hatch_build_py,
                "README.md": readme_md,
            },
        )

    def dump(self, clobber: bool = False, update: bool = False) -> None:
        """Dump the artifacts to disk.

        Args:
            clobber: Whether to clobber an existing build directory
            update: Whether to carry over the lockfile from the clobbered directory

        Raises:
            ValueError: If README.md is not set
            FileExistsError: If the release directory exists and clobber is False
            FileNotFoundError: If update is True but required files are missing

        Examples:
            >>> # artifacts = WorkflowArtifacts(...)  # doctest: +SKIP
            >>> # artifacts.dump(clobber=True)  # doctest: +SKIP
        """
        if not self.readme_md:
            raise ValueError("README.md must be set before dumping artifacts.")

        if self.release_dir.exists() and not clobber:
            raise FileExistsError(
                f"Path '{self.release_dir}' already exists. Set clobber=True to overwrite."
            )
        if self.release_dir.exists() and clobber and not self.release_dir.is_dir():
            raise FileExistsError(f"Cannot clobber existing '{self.release_dir}'; not a directory.")
        if self.release_dir.exists() and clobber:
            if update:
                lockfile = self.release_dir.joinpath("pixi.lock")
                version_yaml = self.release_dir.joinpath("VERSION.yaml")
                readme_md_file = self.release_dir.joinpath("README.md")
                if not all(p.exists() for p in (lockfile, version_yaml, readme_md_file)):
                    raise FileNotFoundError(
                        f"To update, all of {(lockfile, version_yaml, readme_md_file)} must exist."
                    )
                prior_lockfile = lockfile.read_text()
                prior_version_yaml = VersionYaml(**yaml.load(version_yaml.read_text()))
                prior_params_sha256 = _params_sha256_from_readme(readme_md_file.read_text())
                new_params_sha256 = _params_sha256_from_readme(self.readme_md)
                new_version = VersionYaml.bump_from(
                    prior_version=prior_version_yaml,
                    prior_params_sha256=prior_params_sha256,
                    new_params_sha256=new_params_sha256,
                )
            shutil.rmtree(self.release_dir)

        self.release_dir.mkdir(parents=True)

        # root artifacts
        self.pixi_toml.dump(self.release_dir.joinpath("pixi.toml"))
        if self.pydot_graph is not None:
            try:
                self.pydot_graph.write_png(path=self.release_dir.joinpath("graph.png"))  # type: ignore[attr-defined]
            except FileNotFoundError:
                import warnings

                warnings.warn(
                    "Graphviz 'dot' binary not found; skipping graph.png generation. "
                    "Install Graphviz to enable workflow visualization.",
                    stacklevel=2,
                )
        if update:
            self.release_dir.joinpath("pixi.lock").write_text(prior_lockfile)
            new_version.dump(self.release_dir.joinpath("VERSION.yaml"))
        else:
            VersionYaml(MAJ=0, MIN=0).dump(self.release_dir.joinpath("VERSION.yaml"))
        for k, v in {
            "Dockerfile": self.dockerfile,
            ".dockerignore": self.dockerignore,
            "pyproject.toml": self.pyproject_toml,
            "hatch_build.py": self.hatch_build_py,
            "README.md": self.readme_md,
        }.items():
            self.release_dir.joinpath(k).write_text(v)
        # tests
        self.tests.dump(self.release_dir)
        # package artifacts
        pkg = self.release_dir.joinpath(self.package_name)
        pkg.mkdir(parents=True)
        self.package.dump(pkg)
