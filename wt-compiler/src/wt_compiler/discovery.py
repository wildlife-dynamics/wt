"""Task discovery via py-rattler and wt-registry CLI.

This module provides the core innovation of the wt-compiler package:
discovering tasks by creating ephemeral rattler environments using py-rattler's
native async API (solve + install) and calling the wt-registry CLI, avoiding
direct Python import dependencies on task libraries.
"""

import asyncio
import errno
import platform as plat
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from rattler import Channel, MatchSpec, Platform, VirtualPackage, install, solve
from wt_contracts.registry import RegistryOutput

from wt_compiler.exceptions import (
    EnvironmentCreationError,
    PyPIInstallError,
    RegistryExecutionError,
    RegistryNotFoundError,
    RegistryNotFoundInEnvError,
)
from wt_compiler.requirements import CHANNELS
from wt_compiler.spec import KnownTask, PyPIRequirement, TaskTag, known_tasks

# Retry configuration for handling transient ENOTEMPTY errors during parallel install
MAX_INSTALL_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 0.5


class DiscoveryResult(NamedTuple):
    """Result of task discovery, containing both tasks and solved package records."""

    tasks: dict[str, dict[str, KnownTask]]
    records: list[Any]  # list[RepoDataRecord] from rattler solve()


def _registry_output_to_known_tasks(
    registry_output: RegistryOutput,
) -> dict[str, dict[str, KnownTask]]:
    """Convert parsed wt-registry CLI output into a known-tasks mapping.

    This is the shared conversion used by every discovery path (the
    ephemeral-solve path and the current-environment path). It maps the
    typed :class:`~wt_contracts.registry.RegistryOutput` into the nested
    ``{function_name: {public_module_path: KnownTask}}`` structure the
    compiler indexes tasks by, disambiguating functions that share a name
    across modules via an incrementing ``registry_ref``.

    Args:
        registry_output: Parsed output of ``wt-registry --format json``.

    Returns:
        Mapping of task function name to ``{public_module_path: KnownTask}``.

    Examples:
        >>> from wt_contracts.registry import RegistryOutput
        >>> out = RegistryOutput(entries={}, version="1.0.0")
        >>> _registry_output_to_known_tasks(out)
        {}
    """
    discovered_tasks: dict[str, dict[str, KnownTask]] = {}

    for entry in registry_output.entries.values():
        # entry is typed as RegistryEntry from wt-contracts
        # Use public_module_path for imports (via __init__.py re-exports)
        public_module_path = entry.public_module_path
        function_name = entry.function_name
        metadata = entry.metadata
        json_schema = dict(entry.json_schema)

        # Build importable reference using public path
        importable_reference = f"{public_module_path}.{function_name}"

        # Parse tags - filter to only known TaskTag values
        tags = [TaskTag(tag) for tag in metadata.tags if tag in [t.value for t in TaskTag]]

        # Create KnownTask from typed RegistryEntry
        known_task = KnownTask(
            importable_reference=importable_reference,
            tags=tags,
            registry_ref=0,
            json_schema=json_schema,
            description=metadata.description or None,
        )

        # Add to discovered_tasks dict
        if function_name not in discovered_tasks:
            # First occurrence of this function name
            discovered_tasks[function_name] = {public_module_path: known_task}
        else:
            # Function name already seen from another module - needs disambiguation
            known_task.registry_ref = len(discovered_tasks[function_name])
            discovered_tasks[function_name][public_module_path] = known_task

    return discovered_tasks


async def discover_tasks_from_requirements(
    requirements: list[MatchSpec],
    channels: list[Channel] | None = None,
    platform: Platform | None = None,
    pypi_requirements: list[PyPIRequirement] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> DiscoveryResult:
    """Discover tasks by creating an ephemeral rattler environment.

    This async function:
    1. Creates a temporary directory
    2. Uses py-rattler to solve and install the conda requirements
    3. Optionally installs PyPI requirements via pip into the environment
    4. Calls wt-registry CLI in that environment
    5. Parses the JSON output
    6. Returns a dictionary of task name -> {module -> KnownTask}

    Args:
        requirements: List of conda package requirements to install
        channels: Optional list of channels (defaults to conda-forge)
        platform: Optional Platform object (defaults to current platform)
        pypi_requirements: Optional list of PyPI requirements to pip-install
        on_progress: Optional callback invoked with a status message at each phase

    Returns:
        DiscoveryResult containing:
            - tasks: Dictionary mapping task names to {module: KnownTask} dicts
            - records: List of RepoDataRecord objects from rattler solve()

    Raises:
        RegistryNotFoundError: If wt-registry is not installed in the environment
        RegistryExecutionError: If wt-registry CLI returns non-zero exit code
        PyPIInstallError: If pip install of a PyPI requirement fails
        json.JSONDecodeError: If CLI output is not valid JSON
        ValueError: If CLI output doesn't match expected schema

    Examples:
        >>> from rattler import MatchSpec
        >>> reqs = [MatchSpec("wt-registry>=0.1.0")]
        >>> # tasks = await discover_tasks_from_requirements(reqs)  # doctest: +SKIP
        >>> # "my_task" in tasks  # doctest: +SKIP
        True
    """
    if channels is None:
        channels = [Channel("conda-forge")]

    if platform is None:
        # Determine current platform
        if sys.platform == "darwin":
            platform = Platform("osx-arm64") if plat.machine() == "arm64" else Platform("osx-64")
        elif sys.platform == "linux":
            platform = Platform("linux-64")
        elif sys.platform == "win32":
            platform = Platform("win-64")
        else:
            platform = Platform("linux-64")  # fallback

    # When PyPI requirements exist, ensure python and uv are in conda requirements
    if pypi_requirements:
        existing_names = {str(r.name.normalized) for r in requirements if r.name}
        if "python" not in existing_names:
            requirements = [MatchSpec("python"), *requirements]
        if "uv" not in existing_names:
            requirements = [*requirements, MatchSpec("uv")]

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        env_path = Path(tmpdir) / "env"

        # Use py-rattler native API to solve and install packages
        if on_progress is not None:
            on_progress("Solving dependencies...")
        records = await _create_environment(
            env_path, requirements, channels, platform, on_progress=on_progress
        )

        # Install PyPI requirements into the environment via uv. We do this as
        # a single bulk `uv pip install` call so uv resolves all path/git/url
        # sources together — sequential calls would re-resolve each
        # requirement's transitive deps independently and could replace
        # path-installed siblings with registry-installed versions.
        # `--reinstall-package <name>` forces uv to replace any
        # already-satisfied install (e.g. a conda-installed wt-* package whose
        # .dist-info is on sys.path) with the explicit source.
        if pypi_requirements:
            if on_progress is not None:
                on_progress("Installing PyPI dependencies...")
            uv_exe = (
                env_path / "Scripts" / "uv.exe"
                if sys.platform == "win32"
                else env_path / "bin" / "uv"
            )
            env_python = (
                env_path / "Scripts" / "python.exe"
                if sys.platform == "win32"
                else env_path / "bin" / "python"
            )
            uv_args: list[str] = [
                str(uv_exe),
                "pip",
                "install",
                "--python",
                str(env_python),
            ]
            for pypi_req in pypi_requirements:
                uv_args.extend(["--reinstall-package", pypi_req.name])
            for pypi_req in pypi_requirements:
                pip_arg = pypi_req.to_pip_install_arg()
                if pip_arg.startswith("-e "):
                    uv_args.extend(["-e", pip_arg[3:]])
                else:
                    uv_args.append(pip_arg)
            uv_result = subprocess.run(  # noqa: ASYNC221, S603  # blocking install is intentional; cmd built from configured tool path
                uv_args,
                capture_output=True,
                text=True,
                check=False,
            )
            if uv_result.returncode != 0:
                raise PyPIInstallError(
                    requirements=list(pypi_requirements),
                    returncode=uv_result.returncode,
                    stdout=uv_result.stdout,
                    stderr=uv_result.stderr,
                )

        # Determine the executable path based on platform
        if sys.platform == "win32":
            wt_registry_exe = env_path / "Scripts" / "wt-registry.exe"
        else:
            wt_registry_exe = env_path / "bin" / "wt-registry"

        # Check if wt-registry executable exists
        if not wt_registry_exe.exists():
            raise RegistryNotFoundError(
                executable_path=wt_registry_exe,
                requirements=requirements,
            )

        # Build CLI command — wt-registry auto-discovers via entry points
        cli_args = [str(wt_registry_exe), "--format", "json"]

        # Call wt-registry CLI in the environment
        if on_progress is not None:
            on_progress("Discovering tasks...")
        result = subprocess.run(  # noqa: ASYNC221, S603  # blocking subprocess is intentional; cmd built from configured tool path
            cli_args,
            capture_output=True,
            text=True,
            check=False,  # Handle errors explicitly
        )

        if result.returncode != 0:
            raise RegistryExecutionError(
                executable_path=wt_registry_exe,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                requirements=requirements,
            )

        # Parse and validate JSON output using wt-contracts schema
        registry_output = RegistryOutput.model_validate_json(result.stdout)

        # Convert to KnownTask instances keyed by function name
        discovered_tasks = _registry_output_to_known_tasks(registry_output)

        return DiscoveryResult(tasks=discovered_tasks, records=records)


async def _create_environment(
    env_path: Path,
    requirements: list[MatchSpec],
    channels: list[Channel],
    platform: Platform,
    on_progress: Callable[[str], None] | None = None,
) -> list[Any]:
    """Create conda environment using py-rattler native API.

    This function handles transient ENOTEMPTY errors that can occur when
    py-rattler installs packages in parallel and multiple packages try to
    write to the same shared directory (like share/doc).

    Args:
        env_path: Path to create the environment
        requirements: List of package requirements (MatchSpec)
        channels: List of channels
        platform: Target platform
        on_progress: Optional callback for progress reporting

    Returns:
        List of RepoDataRecord objects from the solved environment

    Raises:
        EnvironmentCreationError: If solving or installation fails after retries
    """
    # Detect virtual packages for the current system (e.g., __osx, __glibc)
    # These are needed for packages with platform-specific requirements
    virtual_packages = VirtualPackage.detect()

    # Solve dependencies
    try:
        records = await solve(
            sources=channels,  # 'channels' renamed to 'sources' in rattler 0.22+
            specs=requirements,
            platforms=[platform, Platform("noarch")],
            virtual_packages=virtual_packages,
        )
    except Exception as e:
        raise EnvironmentCreationError(
            env_path=env_path,
            requirements=requirements,
            original_error=e,
            phase="solve",
        ) from e

    # Create dedicated cache directory (persists across retries)
    cache_dir = env_path.parent / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    if on_progress is not None:
        on_progress("Installing packages...")

    # Install solved packages with retry logic for transient ENOTEMPTY errors
    last_error: Exception | None = None
    backoff = INITIAL_BACKOFF_SECONDS

    for attempt in range(1, MAX_INSTALL_RETRIES + 1):
        # Ensure clean env_path and cache_dir for each attempt
        # Both must be cleaned to avoid stale state from partial installs
        if env_path.exists():
            shutil.rmtree(env_path, ignore_errors=True)
        env_path.mkdir(parents=True, exist_ok=True)
        if attempt > 1:
            # Clean cache on retry to avoid stale extraction artifacts
            if cache_dir.exists():
                shutil.rmtree(cache_dir, ignore_errors=True)
            cache_dir.mkdir(parents=True, exist_ok=True)

        try:
            await install(
                records=records,
                target_prefix=str(env_path),
                platform=platform,
                cache_dir=cache_dir,
            )
            return records  # Success
        except Exception as e:  # noqa: BLE001  # retry on any rattler install error; classified below
            last_error = e
            # Check if this is a retryable ENOTEMPTY error
            # py-rattler raises its own exception types (LinkError, ExtractError, IoError)
            # that are NOT OSError subclasses but contain "ENOTEMPTY" or
            # "Directory not empty" in the message
            error_str = str(e).lower()
            is_enotempty = (
                (isinstance(e, OSError) and e.errno == errno.ENOTEMPTY)
                or "enotempty" in error_str
                or "directory not empty" in error_str
            )
            if is_enotempty and attempt < MAX_INSTALL_RETRIES:
                # Inform user about retry so they understand why progress restarts
                print(
                    f"Installation interrupted (directory conflict), "
                    f"retrying ({attempt + 1}/{MAX_INSTALL_RETRIES})...",
                    file=sys.stderr,
                )
                await asyncio.sleep(backoff)
                backoff *= 2.0
                continue
            break

    raise EnvironmentCreationError(
        env_path=env_path,
        requirements=requirements,
        original_error=last_error if last_error else RuntimeError("Unknown error"),
        phase="install",
    ) from last_error


async def populate_known_tasks(
    requirements: list[MatchSpec],
    channels: list[Channel] | None = None,
    pypi_requirements: list[PyPIRequirement] | None = None,
    on_progress: Callable[[str], None] | None = None,
    **kwargs: Any,  # noqa: ANN401  # forwarded to discover_tasks_from_requirements
) -> DiscoveryResult:
    """Discover tasks and populate the global known_tasks dictionary.

    This async convenience function calls discover_tasks_from_requirements
    and updates the global known_tasks dict in spec.py.

    Args:
        requirements: List of package requirements to install
        channels: Optional list of channels to search for packages.
            If not provided, defaults to conda-forge in discover_tasks_from_requirements.
            For custom package channels, this parameter must be provided.
        pypi_requirements: Optional list of PyPI requirements to pip-install
        on_progress: Optional callback invoked with a status message at each phase
        **kwargs: Additional arguments to pass to discover_tasks_from_requirements

    Returns:
        DiscoveryResult containing tasks and solved records

    Examples:
        >>> from rattler import MatchSpec
        >>> from wt_compiler.spec import known_tasks
        >>> reqs = [MatchSpec("my-task-library>=1.0.0")]
        >>> # await populate_known_tasks(reqs)  # doctest: +SKIP
        >>> # len(known_tasks) > 0  # doctest: +SKIP
        True
    """
    result = await discover_tasks_from_requirements(
        requirements,
        channels=channels,
        pypi_requirements=pypi_requirements,
        on_progress=on_progress,
        **kwargs,
    )
    known_tasks.clear()
    known_tasks.update(result.tasks)
    return result


def discover_tasks_from_current_env(
    packages: list[str] | None = None,
    registry_exe: str | Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> DiscoveryResult:
    """Discover tasks by running wt-registry in the *current* environment.

    Unlike :func:`discover_tasks_from_requirements`, this performs **no**
    dependency solve and creates **no** ephemeral environment. It assumes
    the task libraries (and ``wt-registry``) are already installed in the
    running interpreter's environment — the situation inside an invoker
    image that bakes in ``ecoscope.platform`` and the ``wt`` stack. It
    simply shells out to the already-installed ``wt-registry --format
    json`` and converts the output.

    Because there is no solve, the returned :class:`DiscoveryResult` has an
    empty ``records`` list; callers that need pinned versions for a README
    fingerprint should source them elsewhere (e.g. an existing
    ``pixi.lock``).

    Args:
        packages: Optional dotted module paths to import for task
            registration, forwarded as ``--package`` flags. Auto-discovery
            via entry points always runs regardless; this only adds
            explicit imports.
        registry_exe: Path to the ``wt-registry`` executable. Defaults to
            the first ``wt-registry`` found on ``PATH``.
        on_progress: Optional callback invoked with a status message.

    Returns:
        DiscoveryResult with discovered tasks and an empty ``records`` list.

    Raises:
        RegistryNotFoundInEnvError: If no ``wt-registry`` executable is
            found in the current environment.
        RegistryExecutionError: If ``wt-registry`` returns a non-zero exit
            code.

    Examples:
        >>> # In an environment with wt-registry and task libraries installed:
        >>> # result = discover_tasks_from_current_env()  # doctest: +SKIP
        >>> # len(result.tasks) > 0  # doctest: +SKIP
        True
    """
    if registry_exe is None:
        found = shutil.which("wt-registry")
        if found is None:
            raise RegistryNotFoundInEnvError()
        registry_exe = found
    registry_exe = Path(registry_exe)
    if not registry_exe.exists():
        raise RegistryNotFoundInEnvError(executable_path=registry_exe)

    cli_args = [str(registry_exe), "--format", "json"]
    for package in packages or []:
        cli_args.extend(["--package", package])

    if on_progress is not None:
        on_progress("Discovering tasks in current environment...")
    result = subprocess.run(  # noqa: S603  # cmd built from a resolved tool path
        cli_args,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RegistryExecutionError(
            executable_path=registry_exe,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            requirements=[],
        )

    registry_output = RegistryOutput.model_validate_json(result.stdout)
    discovered_tasks = _registry_output_to_known_tasks(registry_output)
    return DiscoveryResult(tasks=discovered_tasks, records=[])


def populate_known_tasks_from_current_env(
    packages: list[str] | None = None,
    registry_exe: str | Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> DiscoveryResult:
    """Discover tasks in the current environment and populate ``known_tasks``.

    Synchronous sibling of :func:`populate_known_tasks` that sources tasks
    from the current environment (no solve) via
    :func:`discover_tasks_from_current_env`, then replaces the global
    ``known_tasks`` dict in ``spec.py``.

    Args:
        packages: Optional dotted module paths forwarded as ``--package``
            flags to wt-registry.
        registry_exe: Optional path to the ``wt-registry`` executable.
        on_progress: Optional callback invoked with a status message.

    Returns:
        DiscoveryResult with discovered tasks and an empty ``records`` list.

    Examples:
        >>> # from wt_compiler.spec import known_tasks  # doctest: +SKIP
        >>> # populate_known_tasks_from_current_env()  # doctest: +SKIP
        >>> # len(known_tasks) > 0  # doctest: +SKIP
        True
    """
    result = discover_tasks_from_current_env(
        packages=packages,
        registry_exe=registry_exe,
        on_progress=on_progress,
    )
    known_tasks.clear()
    known_tasks.update(result.tasks)
    return result


async def discover_tasks_from_spec_requirements(
    spec_requirements: list[Any],  # SpecRequirement from spec.py
    **kwargs: Any,  # noqa: ANN401  # forwarded to populate_known_tasks
) -> DiscoveryResult:
    """Discover tasks from Spec requirements.

    Converts SpecRequirement objects to MatchSpec and discovers tasks.

    Args:
        spec_requirements: List of SpecRequirement objects
        **kwargs: Additional arguments to pass to discover_tasks_from_requirements

    Returns:
        DiscoveryResult containing tasks and solved records

    Examples:
        >>> # from wt_compiler.spec import SpecRequirement  # doctest: +SKIP
        >>> # reqs = [SpecRequirement(name="lib", version=">=1.0")]  # doctest: +SKIP
        >>> # tasks = await discover_tasks_from_spec_requirements(reqs)  # doctest: +SKIP
    """
    # Convert SpecRequirements to MatchSpec
    match_specs = []
    channels = []

    for req in spec_requirements:
        # Build matchspec string with channel
        channel = req.channel
        channels.append(channel)

        # Create MatchSpec
        # MatchSpec format: "channel::package version"
        matchspec_str = f"{channel.name or channel.base_url}::{req.name} {req.version.version}"
        match_specs.append(MatchSpec(matchspec_str))

    # Remove duplicate channels from spec requirements
    unique_channels = list({c.name or c.base_url: c for c in channels}.values())

    # Add all known channels for transitive dependency resolution
    # (only needed when there are actual conda requirements from custom channels)
    if spec_requirements:
        for known_channel in CHANNELS:
            key = known_channel.name or known_channel.base_url
            if key not in {c.name or c.base_url for c in unique_channels}:
                unique_channels.append(known_channel)

    return await discover_tasks_from_requirements(
        match_specs,
        channels=unique_channels,
        **kwargs,
    )
