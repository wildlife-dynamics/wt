"""Task discovery via py-rattler and wt-registry CLI.

This module provides the core innovation of the wt-compiler package:
discovering tasks by creating ephemeral rattler environments using py-rattler's
native async API (solve + install) and calling the wt-registry CLI, avoiding
direct Python import dependencies on task libraries.
"""

import asyncio
import errno
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from rattler import Channel, MatchSpec, Platform, VirtualPackage, install, solve
from wt_contracts.registry import RegistryOutput

from wt_compiler.exceptions import (
    EnvironmentCreationError,
    RegistryExecutionError,
    RegistryNotFoundError,
)
from wt_compiler.requirements import CHANNELS
from wt_compiler.spec import KnownTask, TaskTag, known_tasks

# Retry configuration for handling transient ENOTEMPTY errors during parallel install
MAX_INSTALL_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 0.5


async def discover_tasks_from_requirements(
    requirements: list[MatchSpec],
    channels: list[Channel] | None = None,
    platform: Platform | None = None,
) -> dict[str, dict[str, KnownTask]]:
    """Discover tasks by creating an ephemeral rattler environment.

    This async function:
    1. Creates a temporary directory
    2. Uses py-rattler to solve and install the requirements
    3. Calls wt-registry CLI in that environment
    4. Parses the JSON output
    5. Returns a dictionary of task name -> {module -> KnownTask}

    Args:
        requirements: List of package requirements to install
        channels: Optional list of channels (defaults to conda-forge)
        platform: Optional Platform object (defaults to current platform)

    Returns:
        Dictionary mapping task names to {module: KnownTask} dicts

    Raises:
        RegistryNotFoundError: If wt-registry is not installed in the environment
        RegistryExecutionError: If wt-registry CLI returns non-zero exit code
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
            import platform as plat

            platform = Platform("osx-arm64") if plat.machine() == "arm64" else Platform("osx-64")
        elif sys.platform == "linux":
            platform = Platform("linux-64")
        elif sys.platform == "win32":
            platform = Platform("win-64")
        else:
            platform = Platform("linux-64")  # fallback

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        env_path = Path(tmpdir) / "env"

        # Use py-rattler native API to solve and install packages
        await _create_environment(env_path, requirements, channels, platform)

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

        # Derive task module paths from requirements
        # Convention: package 'foo-bar' has tasks in 'foo_bar.tasks'
        task_modules = []
        for req in requirements:
            # Extract package name from MatchSpec (convert to string)
            pkg_name = str(req.name.normalized) if req.name else None
            # Skip wt-registry itself and other non-task packages
            if pkg_name and not pkg_name.startswith("wt-"):
                # Convert package name to module path: foo-bar -> foo_bar.tasks
                module_path = pkg_name.replace("-", "_") + ".tasks"
                task_modules.append(module_path)

        # Build CLI command with --package arguments
        cli_args = [str(wt_registry_exe), "--format", "json"]
        for module in task_modules:
            cli_args.extend(["--package", module])

        # Call wt-registry CLI in the environment
        result = subprocess.run(
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

        # Convert to KnownTask instances and populate known_tasks dict
        discovered_tasks: dict[str, dict[str, KnownTask]] = {}

        for _, entry in registry_output.entries.items():
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
                description=metadata.description,
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


async def _create_environment(
    env_path: Path,
    requirements: list[MatchSpec],
    channels: list[Channel],
    platform: Platform,
) -> None:
    """Create conda environment using py-rattler native API.

    This function handles transient ENOTEMPTY errors that can occur when
    py-rattler installs packages in parallel and multiple packages try to
    write to the same shared directory (like share/doc).

    Args:
        env_path: Path to create the environment
        requirements: List of package requirements (MatchSpec)
        channels: List of channels
        platform: Target platform

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
            return  # Success
        except Exception as e:
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
    **kwargs: Any,
) -> None:
    """Discover tasks and populate the global known_tasks dictionary.

    This async convenience function calls discover_tasks_from_requirements
    and updates the global known_tasks dict in spec.py.

    Args:
        requirements: List of package requirements to install
        channels: Optional list of channels to search for packages.
            If not provided, defaults to conda-forge in discover_tasks_from_requirements.
            For custom package channels, this parameter must be provided.
        **kwargs: Additional arguments to pass to discover_tasks_from_requirements

    Examples:
        >>> from rattler import MatchSpec
        >>> from wt_compiler.spec import known_tasks
        >>> reqs = [MatchSpec("my-task-library>=1.0.0")]
        >>> # await populate_known_tasks(reqs)  # doctest: +SKIP
        >>> # len(known_tasks) > 0  # doctest: +SKIP
        True
    """
    discovered = await discover_tasks_from_requirements(requirements, channels=channels, **kwargs)
    known_tasks.clear()
    known_tasks.update(discovered)


async def discover_tasks_from_spec_requirements(
    spec_requirements: list[Any],  # SpecRequirement from spec.py
    **kwargs: Any,
) -> dict[str, dict[str, KnownTask]]:
    """Discover tasks from Spec requirements.

    Converts SpecRequirement objects to MatchSpec and discovers tasks.

    Args:
        spec_requirements: List of SpecRequirement objects
        **kwargs: Additional arguments to pass to discover_tasks_from_requirements

    Returns:
        Dictionary mapping task names to {module: KnownTask} dicts

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
    # This uses CHANNELS from requirements.py as the single source of truth
    for known_channel in CHANNELS:
        key = known_channel.name or known_channel.base_url
        if key not in {c.name or c.base_url for c in unique_channels}:
            unique_channels.append(known_channel)

    return await discover_tasks_from_requirements(
        match_specs,
        channels=unique_channels,
        **kwargs,
    )
