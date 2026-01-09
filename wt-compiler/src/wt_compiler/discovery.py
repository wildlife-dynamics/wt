"""Task discovery via wt-registry CLI subprocess calls.

This module provides the core innovation of the wt-compiler package:
discovering tasks by creating ephemeral rattler environments and calling
the wt-registry CLI, avoiding direct Python import dependencies on task libraries.
"""

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from rattler import Channel, MatchSpec
from wt_contracts.registry import RegistryOutput

from wt_compiler.spec import KnownTask, TaskTag, known_tasks


def discover_tasks_from_requirements(
    requirements: list[MatchSpec],
    channels: list[Channel] | None = None,
    platform: str | None = None,
) -> dict[str, dict[str, KnownTask]]:
    """Discover tasks by creating an ephemeral rattler environment.

    This function:
    1. Creates a temporary directory
    2. Uses rattler to solve and install the requirements
    3. Calls wt-registry CLI in that environment
    4. Parses the JSON output
    5. Returns a dictionary of task name -> {module -> KnownTask}

    Args:
        requirements: List of package requirements to install
        channels: Optional list of channels (defaults to conda-forge)
        platform: Optional platform string (defaults to current platform)

    Returns:
        Dictionary mapping task names to {module: KnownTask} dicts

    Raises:
        subprocess.CalledProcessError: If wt-registry CLI fails
        json.JSONDecodeError: If CLI output is not valid JSON
        ValueError: If CLI output doesn't match expected schema

    Examples:
        >>> from rattler import MatchSpec
        >>> reqs = [MatchSpec("wt-registry>=0.1.0")]
        >>> # tasks = discover_tasks_from_requirements(reqs)  # doctest: +SKIP
        >>> # "my_task" in tasks  # doctest: +SKIP
        True
    """
    if channels is None:
        channels = [Channel("conda-forge")]

    if platform is None:
        # Determine current platform
        if sys.platform == "darwin":
            import platform as plat

            platform = "osx-arm64" if plat.machine() == "arm64" else "osx-64"
        elif sys.platform == "linux":
            platform = "linux-64"
        elif sys.platform == "win32":
            platform = "win-64"
        else:
            platform = "linux-64"  # fallback

    with tempfile.TemporaryDirectory() as tmpdir:
        env_path = Path(tmpdir) / "env"

        # NOTE: The rattler-py API for solve/install may vary between versions.
        # Some versions have async APIs (solve/install are coroutines).
        # For reliability, we use the subprocess fallback with pixi/mamba/conda.
        # TODO: Update to use rattler-py native API when stable and well-documented
        _install_via_subprocess(env_path, requirements, channels, platform)

        # Determine the executable path based on platform
        if sys.platform == "win32":
            wt_registry_exe = env_path / "Scripts" / "wt-registry.exe"
        else:
            wt_registry_exe = env_path / "bin" / "wt-registry"

        # Call wt-registry CLI in the environment
        result = subprocess.run(
            [str(wt_registry_exe), "--format", "json"],
            capture_output=True,
            text=True,
            check=True,
        )

        # Parse and validate JSON output using wt-contracts schema
        registry_output = RegistryOutput.model_validate_json(result.stdout)

        # Convert to KnownTask instances and populate known_tasks dict
        discovered_tasks: dict[str, dict[str, KnownTask]] = {}

        for fqn, entry in registry_output.entries.items():
            # entry is typed as RegistryEntry from wt-contracts
            module_path = entry.module_path
            function_name = entry.function_name
            metadata = entry.metadata
            json_schema = dict(entry.json_schema)

            # Build importable reference
            importable_reference = f"{module_path}.{function_name}"

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
                discovered_tasks[function_name] = {}

            # Handle duplicate task names by incrementing registry_ref
            if module_path in discovered_tasks[function_name]:
                # This shouldn't happen, but handle it gracefully
                known_task.registry_ref = len(discovered_tasks[function_name])

            discovered_tasks[function_name][module_path] = known_task

        return discovered_tasks


def _install_via_subprocess(
    env_path: Path,
    requirements: list[MatchSpec],
    channels: list[Channel],
    platform: str,
) -> None:
    """Fallback installation via subprocess using pixi or mamba.

    This is used when rattler-py native API is not available or fails.

    Args:
        env_path: Path to create the environment
        requirements: List of package requirements
        channels: List of channels
        platform: Platform string

    Raises:
        RuntimeError: If no suitable package manager is found
        subprocess.CalledProcessError: If installation fails
    """
    # Try to find a suitable package manager
    for cmd in ["pixi", "mamba", "conda"]:
        if _command_exists(cmd):
            # Build channel args
            channel_args = []
            for channel in channels:
                channel_args.extend(["-c", channel.name or str(channel)])

            # Build requirement args
            req_args = [str(req) for req in requirements]

            # Create environment
            create_cmd = (
                [
                    cmd,
                    "create",
                    "-p",
                    str(env_path),
                    "-y",
                    "--platform",
                    platform,
                ]
                + channel_args
                + req_args
            )

            subprocess.run(create_cmd, check=True, capture_output=True)
            return

    raise RuntimeError(
        "No suitable package manager found (pixi, mamba, or conda required). "
        "Please install one to use task discovery."
    )


def _command_exists(command: str) -> bool:
    """Check if a command exists in PATH.

    Args:
        command: Command name to check

    Returns:
        True if command exists, False otherwise
    """
    try:
        subprocess.run(
            [command, "--version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def populate_known_tasks(requirements: list[MatchSpec], **kwargs: Any) -> None:
    """Discover tasks and populate the global known_tasks dictionary.

    This is a convenience function that calls discover_tasks_from_requirements
    and updates the global known_tasks dict in spec.py.

    Args:
        requirements: List of package requirements to install
        **kwargs: Additional arguments to pass to discover_tasks_from_requirements

    Examples:
        >>> from rattler import MatchSpec
        >>> from wt_compiler.spec import known_tasks
        >>> reqs = [MatchSpec("my-task-library>=1.0.0")]
        >>> # populate_known_tasks(reqs)  # doctest: +SKIP
        >>> # len(known_tasks) > 0  # doctest: +SKIP
        True
    """
    discovered = discover_tasks_from_requirements(requirements, **kwargs)
    known_tasks.clear()
    known_tasks.update(discovered)


def discover_tasks_from_spec_requirements(
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
        >>> # reqs = [SpecRequirement(name="my-lib", version=">=1.0", channel="conda-forge")]  # doctest: +SKIP
        >>> # tasks = discover_tasks_from_spec_requirements(reqs)  # doctest: +SKIP
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

    # Remove duplicate channels
    unique_channels = list({c.name or c.base_url: c for c in channels}.values())

    return discover_tasks_from_requirements(
        match_specs,
        channels=unique_channels,
        **kwargs,
    )
