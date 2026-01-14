"""Pytest configuration and fixtures for reverse integration tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from helpers.compile import compile_workflow, CompileResult
from helpers.diff import (
    check_diff_allowlist,
    get_changed_files,
    DiffResult,
)
from helpers.git import clone_at_ref, CloneResult


# Path to this file's directory (src/) and parent (reverse_integration/)
SRC_DIR = Path(__file__).parent
REVERSE_INTEGRATION_DIR = SRC_DIR.parent
MANIFEST_PATH = REVERSE_INTEGRATION_DIR / "manifest.yaml"


@dataclass
class RepoConfig:
    """Configuration for a single repo to test."""

    url: str
    ref: str
    spec_path: str
    generated_path: str
    spec_name: str | None = None  # For monorepos: identifies which spec (e.g., "etl")

    @property
    def id(self) -> str:
        """Return a unique identifier for this config."""
        # Extract repo name from URL
        repo_name = self.url.rstrip("/").split("/")[-1]
        if self.spec_name:
            return f"{repo_name}/{self.spec_name}@{self.ref}"
        return f"{repo_name}@{self.ref}"


@dataclass
class Workspace:
    """A cloned repository workspace ready for testing."""

    repo_config: RepoConfig
    clone_result: CloneResult
    compile_result: CompileResult | None = None
    diff_result: DiffResult | None = None


def load_manifest() -> dict[str, Any]:
    """Load the manifest.yaml file."""
    with open(MANIFEST_PATH) as f:
        return yaml.safe_load(f)


def _derive_spec_name(spec_path: str) -> str:
    """Derive a spec name from the spec path for monorepo entries.

    For a path like 'workflows/etl/spec.yaml', returns 'etl'.
    """
    from pathlib import PurePosixPath

    path = PurePosixPath(spec_path)
    # Use the parent directory name as the spec name
    return path.parent.name or path.stem


def get_repo_configs(
    manifest: dict[str, Any],
    repo_url_filter: str | None = None,
    ref_override: str | None = None,
) -> list[RepoConfig]:
    """
    Extract repo configurations from manifest.

    Args:
        manifest: Parsed manifest dict
        repo_url_filter: If provided, only return configs for this URL
        ref_override: If provided, override all refs with this value

    Returns:
        List of RepoConfig objects
    """
    configs = []

    for repo in manifest.get("repos", []):
        url = repo["url"]

        # Apply URL filter if provided
        if repo_url_filter and url != repo_url_filter:
            continue

        # Handle single spec or multiple specs
        if "specs" in repo:
            # Multiple specs in monorepo
            for spec_config in repo["specs"]:
                configs.append(
                    RepoConfig(
                        url=url,
                        ref=ref_override or repo.get("ref", "main"),
                        spec_path=spec_config["spec_path"],
                        generated_path=spec_config["generated_path"],
                        spec_name=_derive_spec_name(spec_config["spec_path"]),
                    )
                )
        else:
            # Single spec
            configs.append(
                RepoConfig(
                    url=url,
                    ref=ref_override or repo.get("ref", "main"),
                    spec_path=repo.get("spec_path", "spec.yaml"),
                    generated_path=repo.get("generated_path", ""),
                )
            )

    return configs


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom CLI options for reverse integration tests."""
    group = parser.getgroup("reverse-integration")

    group.addoption(
        "--repo-url",
        action="store",
        default=None,
        help="Test a single repo URL (ad-hoc testing, overrides manifest)",
    )

    group.addoption(
        "--repo-ref",
        action="store",
        default=None,
        help="Override git ref for all repos (e.g., 'main', 'v1.0.0', 'latest-release')",
    )

    group.addoption(
        "--repo-auth",
        action="store",
        default=None,
        help="Auth token for private repos (format: 'token:TOKEN')",
    )

    group.addoption(
        "--cases",
        action="store",
        default=None,
        help="Comma-separated list of test cases to run (default: all)",
    )

    group.addoption(
        "--skip-generated-tests",
        action="store_true",
        default=False,
        help="Skip running the generated workflow tests",
    )

    group.addoption(
        "--manifest-item",
        action="store",
        default=None,
        help="Run tests for a specific manifest item by ID (e.g., 'events@main')",
    )


@pytest.fixture(scope="session")
def manifest() -> dict[str, Any]:
    """Load the manifest.yaml file."""
    return load_manifest()


@pytest.fixture(scope="session")
def diff_allowlist(manifest: dict[str, Any]) -> list[str]:
    """Get the list of files allowed to have diffs."""
    return manifest.get("diff_allowlist", ["README.md", "pixi.lock", "VERSION.yaml"])


@pytest.fixture(scope="session")
def auth_token(request: pytest.FixtureRequest) -> str | None:
    """Get the authentication token from CLI options."""
    auth = request.config.getoption("--repo-auth")
    if auth and auth.startswith("token:"):
        return auth[6:]  # Strip 'token:' prefix
    return None


@pytest.fixture(scope="session")
def selected_cases(request: pytest.FixtureRequest) -> list[str] | None:
    """Get the list of test cases to run from CLI options."""
    cases = request.config.getoption("--cases")
    if cases:
        return [c.strip() for c in cases.split(",")]
    return None


def get_repo_configs_for_session(config: pytest.Config) -> list[RepoConfig]:
    """
    Get repo configs based on CLI options and manifest.

    Args:
        config: Pytest Config object (from metafunc.config or request.config)

    Handles:
    - --repo-url for ad-hoc single repo testing
    - --repo-ref for ref overrides
    - --manifest-item for filtering to a specific item by ID
    - 'latest-release' special ref value
    """
    manifest = load_manifest()

    repo_url = config.getoption("--repo-url")
    ref_override = config.getoption("--repo-ref")
    manifest_item = config.getoption("--manifest-item")

    if repo_url:
        # Ad-hoc single repo testing
        return [
            RepoConfig(
                url=repo_url,
                ref=ref_override or "main",
                spec_path="spec.yaml",
                generated_path="",
            )
        ]

    configs = get_repo_configs(manifest, ref_override=ref_override)

    # Filter to specific manifest item if requested
    if manifest_item:
        matching = [c for c in configs if c.id == manifest_item]
        if not matching:
            available_ids = [c.id for c in configs]
            raise pytest.UsageError(
                f"Manifest item '{manifest_item}' not found. "
                f"Available items: {', '.join(available_ids)}"
            )
        return matching

    return configs


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Generate test parameters from manifest repos."""
    if "repo_config" in metafunc.fixturenames:
        configs = get_repo_configs_for_session(metafunc.config)
        metafunc.parametrize(
            "repo_config",
            configs,
            ids=[c.id for c in configs],
        )


@pytest.fixture
def repo_workspace(
    repo_config: RepoConfig,
    tmp_path: Path,
    auth_token: str | None,
    request: pytest.FixtureRequest,
) -> Workspace:
    """
    Clone a repository and prepare it for testing.

    This fixture clones the repo to a temp directory and returns
    a Workspace object with the clone result.
    """
    ref = repo_config.ref

    # Handle 'latest-release' special ref
    if ref == "latest-release":
        from helpers.git import get_latest_release_tag

        tag = get_latest_release_tag(repo_config.url, auth_token)
        if tag is None:
            pytest.skip(f"No releases found for {repo_config.url}")
        ref = tag

    clone_result = clone_at_ref(
        url=repo_config.url,
        dest=tmp_path / "repo",
        ref=ref,
        auth_token=auth_token,
    )

    return Workspace(
        repo_config=repo_config,
        clone_result=clone_result,
    )


@pytest.fixture
def compiled_workspace(
    repo_workspace: Workspace,
    diff_allowlist: list[str],
) -> Workspace:
    """
    Compile the workflow in a cloned repository.

    This fixture runs wt-compiler on the spec.yaml and checks for diffs.
    """
    repo_path = repo_workspace.clone_result.path

    # Run the compiler
    compile_result = compile_workflow(
        repo_path=repo_path,
        spec_path=repo_workspace.repo_config.spec_path,
        generated_path=repo_workspace.repo_config.generated_path or None,
        clobber=True,
        update=False,
    )

    repo_workspace.compile_result = compile_result

    # Check for diffs if compilation succeeded
    if compile_result.success:
        changed_files = get_changed_files(repo_path)
        diff_result = check_diff_allowlist(
            changed_files,
            diff_allowlist,
            repo_workspace.repo_config.generated_path or None,
        )
        repo_workspace.diff_result = diff_result

    return repo_workspace


@pytest.fixture
def test_cases(
    repo_workspace: Workspace,
    selected_cases: list[str] | None,
) -> list[str]:
    """
    Get the list of test cases to run for a repo.

    Parses test-cases.yaml from the repo and applies any case filters.
    """
    repo_path = repo_workspace.clone_result.path
    test_cases_path = repo_path / "test-cases.yaml"

    if not test_cases_path.exists():
        return []

    with open(test_cases_path) as f:
        cases_data = yaml.safe_load(f)

    # Get all case names (keys in the YAML)
    all_cases = list(cases_data.keys()) if cases_data else []

    # Apply filter if provided
    if selected_cases:
        return [c for c in all_cases if c in selected_cases]

    return all_cases
