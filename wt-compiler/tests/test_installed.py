"""Tests for checking spec requirements against the installed environment."""

import json
import platform
from importlib.metadata import version
from pathlib import Path

import pytest

from wt_compiler.exceptions import InstalledRequirementsError
from wt_compiler.installed import resolve_installed_requirements
from wt_compiler.spec import PyPIRequirement, SpecRequirement

PLATFORM_CHANNEL = "https://repo.prefix.dev/ecoscope-workflows/"


def _conda_meta(prefix: Path, name: str, version_: str, channel: str = PLATFORM_CHANNEL) -> None:
    conda_meta = prefix / "conda-meta"
    conda_meta.mkdir(exist_ok=True)
    record = {"name": name, "version": version_, "channel": channel}
    (conda_meta / f"{name}-{version_}-pyh_0.json").write_text(json.dumps(record))


def _req(name: str, version_: str) -> SpecRequirement:
    return SpecRequirement(name=name, version=version_, channel=PLATFORM_CHANNEL)


def test_pins_conda_requirement_to_installed_version(tmp_path: Path) -> None:
    _conda_meta(tmp_path, "ecoscope-platform", "2.23.0")

    [pinned] = resolve_installed_requirements([_req("ecoscope-platform", "2.*")], prefix=tmp_path)

    assert pinned.name == "ecoscope-platform"
    assert str(pinned.version.version) == "==2.23.0"
    assert pinned.channel.base_url == PLATFORM_CHANNEL


def test_reports_every_problem_together(tmp_path: Path) -> None:
    _conda_meta(tmp_path, "ecoscope-platform", "2.23.0")

    with pytest.raises(InstalledRequirementsError) as excinfo:
        resolve_installed_requirements(
            [_req("ecoscope-platform", "==2.26.0"), _req("not-a-real-package", "*")],
            prefix=tmp_path,
        )

    assert excinfo.value.problems == [
        "ecoscope-platform ==2.26.0 is required, but 2.23.0 is installed",
        "not-a-real-package is not installed",
    ]


def test_longer_name_sharing_the_prefix_is_not_a_match(tmp_path: Path) -> None:
    _conda_meta(tmp_path, "ecoscope-platform-extras", "9.9.9")

    with pytest.raises(InstalledRequirementsError, match="ecoscope-platform is not installed"):
        resolve_installed_requirements([_req("ecoscope-platform", "*")], prefix=tmp_path)


def test_falls_back_to_python_distributions(tmp_path: Path) -> None:
    """Without a conda record, a pip/uv-installed distribution satisfies the requirement."""
    [pinned] = resolve_installed_requirements(
        [SpecRequirement(name="pydantic", version=">=2")], prefix=tmp_path
    )

    assert str(pinned.version.version) == f"=={version('pydantic')}"


def test_python_outside_a_conda_env_is_the_running_interpreter(tmp_path: Path) -> None:
    [pinned] = resolve_installed_requirements(
        [SpecRequirement(name="python", version=">=3.10")], prefix=tmp_path
    )

    assert str(pinned.version.version) == f"=={platform.python_version()}"


def test_pypi_requirements_are_checked_for_presence_only(tmp_path: Path) -> None:
    present = PyPIRequirement(name="pydantic", url="https://example.com/pydantic.whl")
    missing = PyPIRequirement(name="not-a-real-package", url="https://example.com/x.whl")

    assert resolve_installed_requirements([present], prefix=tmp_path) == []
    with pytest.raises(InstalledRequirementsError, match="not-a-real-package is not installed"):
        resolve_installed_requirements([missing], prefix=tmp_path)
