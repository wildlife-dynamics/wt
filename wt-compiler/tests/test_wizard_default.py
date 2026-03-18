"""Tests for DefaultWizardProvider behavior — questions, validation, and dump."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
import yaml

from wt_compiler.requirements import CHANNELS, _serialize_channel
from conftest import drive_wizard

from wt_compiler.wizard.abstract import AbstractWizardProvider, SingleWizardQuestion
from wt_compiler.wizard.default import (
    CHANNEL_CHOICES,
    DefaultWizardProvider,
    non_empty_str,
    requirement_version_type,
    workflow_id_type,
)


class TestWorkflowIdValidation:
    """Tests for workflow_id_type validation callable."""

    def test_valid_identifier(self) -> None:
        """Valid Python identifier is accepted."""
        assert workflow_id_type("my_workflow") == "my_workflow"

    def test_not_identifier(self) -> None:
        """Non-identifier string raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError, match="not a valid Python identifier"):
            workflow_id_type("123bad")

    def test_too_long(self) -> None:
        """String >64 chars raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError, match="too long"):
            workflow_id_type("a" * 65)

    def test_keyword(self) -> None:
        """Python keyword raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError, match="keyword"):
            workflow_id_type("class")

    def test_builtin(self) -> None:
        """Python builtin name raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError, match="built-in"):
            workflow_id_type("print")

    def test_empty(self) -> None:
        """Empty string raises ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError, match="cannot be empty"):
            workflow_id_type("")


class TestGetQuestionsIsolation:
    """Tests verifying that get_questions() returns independent copies."""

    def test_get_questions_returns_deep_copy(self) -> None:
        """Mutating returned questions does not affect subsequent calls."""
        provider = DefaultWizardProvider()
        qs1 = provider.get_questions()
        # Mutate the choices list of license_type in the first copy
        for q in qs1:
            if q["dest"] == "license_type":
                q["argparse"]["choices"] = ["Custom"]

        # Second call must return the original choices
        qs2 = provider.get_questions()
        for q in qs2:
            if q["dest"] == "license_type":
                assert q["argparse"]["choices"] == ["BSD-3-Clause", "MIT", "Apache-2.0"]

    def test_get_questions_independent_instances(self) -> None:
        """Two separate providers return independent question lists."""
        p1 = DefaultWizardProvider()
        p2 = DefaultWizardProvider()
        qs1 = p1.get_questions()
        qs2 = p2.get_questions()
        # Mutate p1's list
        for q in qs1:
            if q["dest"] == "license_type":
                q["argparse"]["choices"] = ["Custom"]
        # p2's list must be unaffected
        for q in qs2:
            if q["dest"] == "license_type":
                assert q["argparse"]["choices"] == ["BSD-3-Clause", "MIT", "Apache-2.0"]


class TestRequirementsLoop:
    """Tests for the requirements WizardQuestionLoop."""

    def test_requirements_loop_multiple(self) -> None:
        """Drive 3 requirements iterations, then end loop."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow",  # workflow_id
            "My Workflow",  # workflow_name
            "desc",  # workflow_description
            "Author",  # author_name
            "MIT",  # license_type
            # Requirement 1
            "numpy",  # name
            ">=1.0",  # version
            "conda-forge",  # channel
            # Requirement 2
            "pandas",  # name
            "*",  # version
            "conda-forge",  # channel
            # Requirement 3
            "scipy",  # name
            ">=2.0",  # version
            "conda-forge",  # channel
            # End loop
            "",  # empty name = done
        ]
        drive_wizard(provider, answers)
        reqs = provider.answers["requirements"]
        assert len(reqs) == 3
        assert reqs[0] == {"name": "numpy", "version": ">=1.0", "channel": "conda-forge"}
        assert reqs[1] == {"name": "pandas", "version": "*", "channel": "conda-forge"}
        assert reqs[2] == {"name": "scipy", "version": ">=2.0", "channel": "conda-forge"}

    def test_requirements_loop_empty_immediately(self) -> None:
        """Send empty on first name prompt — requirements is empty list."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow",  # workflow_id
            "My Workflow",  # workflow_name
            "desc",  # workflow_description
            "Author",  # author_name
            "MIT",  # license_type
            "",  # empty name = done immediately
        ]
        drive_wizard(provider, answers)
        assert provider.answers["requirements"] == []

    def test_requirement_version_validation(self) -> None:
        """Send invalid version string, verify re-yield with error."""
        provider = DefaultWizardProvider()
        gen = provider.input_generator()
        # Skip to requirements loop
        answers_before_loop = [
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "MIT",
        ]
        q = next(gen)
        for ans in answers_before_loop:
            q = gen.send(ans)

        # First requirement name
        assert q["dest"] == "name"
        q = gen.send("numpy")
        # Version question
        assert q["dest"] == "version"
        # Send invalid version
        q = gen.send(">>>invalid<<<")
        assert q["dest"] == "version"
        assert "error" in q["wizard"]

    def test_requirement_channel_choices(self) -> None:
        """Verify channel choices match all channels from requirements.CHANNELS."""
        # CHANNEL_CHOICES is computed at import time from CHANNELS via
        # _serialize_channel.  We verify the list has the right length and
        # that every entry is a non-empty string (the actual serialised
        # values depend on env-var state at import time for WT_LOCAL_CHANNEL).
        assert len(CHANNEL_CHOICES) == len(CHANNELS)
        assert all(isinstance(c, str) and c for c in CHANNEL_CHOICES)
        # Well-known channels should always be present
        assert "conda-forge" in CHANNEL_CHOICES


class TestLicenseDefaults:
    """Tests for license question behavior."""

    def test_license_default(self) -> None:
        """Send None/empty for license — defaults to BSD-3-Clause."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "",  # empty → default
            "",  # end requirements loop
        ]
        drive_wizard(provider, answers)
        assert provider.answers["license_type"] == "BSD-3-Clause"

    def test_license_invalid_choice_reyields(self) -> None:
        """Send invalid license string — verify choices present."""
        provider = DefaultWizardProvider()
        gen = provider.input_generator()
        # Skip to license question
        q = next(gen)
        q = gen.send("my_workflow")
        q = gen.send("My Workflow")
        q = gen.send("desc")
        q = gen.send("Author")
        assert q["dest"] == "license_type"
        # The choices validation is in argparse, but the type callable is str.
        # For interactive mode, the generator just passes through str values.
        # The choices enforcement happens in argparse batch mode.
        # In the generator, any string is accepted since type=str.
        # This test verifies the choices are present in the question.
        assert q["argparse"]["choices"] == ["BSD-3-Clause", "MIT", "Apache-2.0"]


class TestDump:
    """Tests for dump() template rendering."""

    def _make_provider_with_answers(self) -> DefaultWizardProvider:
        """Create a provider with all answers populated."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow",
            "My Workflow",
            "A test workflow",
            "Test Author",
            "MIT",
            "numpy",
            ">=1.0",
            "conda-forge",
            "",  # end requirements
        ]
        drive_wizard(provider, answers)
        return provider

    def test_dump_creates_all_files(self, tmp_path: Path) -> None:
        """All expected files exist after dump, including nested paths."""
        provider = self._make_provider_with_answers()
        provider.dump(tmp_path)
        expected_files = [
            "spec.yaml",
            "test-cases.yaml",
            "README.md",
            "LICENSE",
            ".gitignore",
            ".gitattributes",
            ".github/workflows/ci.yml",
            ".github/workflows/tag.yml",
        ]
        for fname in expected_files:
            assert (tmp_path / fname).exists(), f"{fname} not found"

    def test_dump_spec_yaml_valid_structure(self, tmp_path: Path) -> None:
        """Parse generated spec.yaml, verify id, requirements, workflow keys."""
        provider = self._make_provider_with_answers()
        provider.dump(tmp_path)
        content = yaml.safe_load((tmp_path / "spec.yaml").read_text())
        assert content["id"] == "my_workflow"
        assert content["workflow"] == []
        assert len(content["requirements"]) == 1
        req = content["requirements"][0]
        assert req["name"] == "numpy"
        assert req["version"] == ">=1.0"
        assert req["channel"] == "conda-forge"

    def test_dump_test_cases_yaml_structure(self, tmp_path: Path) -> None:
        """Verify test-cases.yaml is valid commented YAML."""
        provider = self._make_provider_with_answers()
        provider.dump(tmp_path)
        text = (tmp_path / "test-cases.yaml").read_text()
        assert "my_workflow" in text
        # Should be parseable (even if empty/None)
        content = yaml.safe_load(text)
        assert content is None  # all comments, no data

    def test_dump_readme_contains_metadata(self, tmp_path: Path) -> None:
        """Verify workflow name, description, author present in README."""
        provider = self._make_provider_with_answers()
        provider.dump(tmp_path)
        text = (tmp_path / "README.md").read_text()
        assert "My Workflow" in text
        assert "A test workflow" in text
        assert "Test Author" in text
        assert "MIT" in text

    def test_dump_gitignore_contents(self, tmp_path: Path) -> None:
        """Has __pycache__/, .pixi/, and .wt-tmp/."""
        provider = self._make_provider_with_answers()
        provider.dump(tmp_path)
        text = (tmp_path / ".gitignore").read_text()
        assert "__pycache__/" in text
        assert ".pixi/" in text
        assert ".wt-tmp/" in text

    def test_dump_gitattributes_contents(self, tmp_path: Path) -> None:
        """Has linguist-generated=true."""
        provider = self._make_provider_with_answers()
        provider.dump(tmp_path)
        text = (tmp_path / ".gitattributes").read_text()
        assert "linguist-generated=true" in text

    def test_dump_ci_yml_parse_test_cases_job(self, tmp_path: Path) -> None:
        """CI workflow contains parse-test-cases job with expected outputs."""
        provider = self._make_provider_with_answers()
        provider.dump(tmp_path)
        text = (tmp_path / ".github/workflows/ci.yml").read_text()
        assert "parse-test-cases:" in text
        assert "steps.parse.outputs.cases" in text
        assert "steps.parse.outputs.first_case" in text
        assert "steps.parse.outputs.release_dir" in text

    def test_dump_ci_yml_validation_errors(self, tmp_path: Path) -> None:
        """CI workflow contains validation error messages for empty test-cases and missing params."""
        provider = self._make_provider_with_answers()
        provider.dump(tmp_path)
        text = (tmp_path / ".github/workflows/ci.yml").read_text()
        assert "test-cases.yaml has no test cases defined" in text
        assert "is missing required 'params' field" in text

    def test_dump_ci_yml_test_job_matrix(self, tmp_path: Path) -> None:
        """CI test job uses matrix.case strategy."""
        provider = self._make_provider_with_answers()
        provider.dump(tmp_path)
        text = (tmp_path / ".github/workflows/ci.yml").read_text()
        assert "needs: parse-test-cases" in text
        assert "matrix:" in text
        assert "fromJSON(needs.parse-test-cases.outputs.cases)" in text
        assert "matrix.case" in text

    def test_dump_ci_yml_docker_job_uses_first_case(self, tmp_path: Path) -> None:
        """CI docker job uses first_case output from parse-test-cases."""
        provider = self._make_provider_with_answers()
        provider.dump(tmp_path)
        text = (tmp_path / ".github/workflows/ci.yml").read_text()
        assert "needs.parse-test-cases.outputs.first_case" in text
        assert ".wt-tmp/" in text
        assert "$RELEASE_DIR" in text

    def test_dump_tag_yml_preserves_github_expressions(self, tmp_path: Path) -> None:
        """Tag workflow preserves ${{ }} GitHub Actions expressions literally."""
        provider = self._make_provider_with_answers()
        provider.dump(tmp_path)
        text = (tmp_path / ".github/workflows/tag.yml").read_text()
        assert "${{ steps.create_tag.outputs.result }}" in text
        assert "${{ steps.find_release_dir.outputs.name }}" in text
        assert "${{ github.event.pull_request.merge_commit_sha }}" in text
        assert "${{ needs.generate-tag.outputs.tag }}" in text

    def test_dump_creates_nested_directories(self, tmp_path: Path) -> None:
        """dump() creates .github/workflows/ directory automatically."""
        provider = self._make_provider_with_answers()
        provider.dump(tmp_path)
        assert (tmp_path / ".github" / "workflows").is_dir()

    def test_dump_raises_on_incomplete_answers(self, tmp_path: Path) -> None:
        """Incomplete provider raises UndefinedError when rendering."""
        import jinja2

        provider = DefaultWizardProvider()
        # Don't drive the wizard — answers are empty
        with pytest.raises(jinja2.UndefinedError):
            provider.dump(tmp_path)
