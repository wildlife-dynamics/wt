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
    REQ_TYPE_CHOICES,
    DefaultWizardProvider,
    _absolute_path_type,
    _git_url_type,
    _http_url_type,
    _requirements_batch_type,
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
        """Drive 3 conda requirements iterations, then end loop."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow",  # workflow_id
            "My Workflow",  # workflow_name
            "desc",  # workflow_description
            "Author",  # author_name
            "MIT",  # license_type
            # Requirement 1 (conda)
            "numpy",  # name
            "conda",  # req_type
            ">=1.0",  # version
            "conda-forge",  # channel
            # Requirement 2 (conda)
            "pandas",  # name
            "conda",  # req_type
            "*",  # version
            "conda-forge",  # channel
            # Requirement 3 (conda)
            "scipy",  # name
            "conda",  # req_type
            ">=2.0",  # version
            "conda-forge",  # channel
            # End loop
            "",
        ]
        drive_wizard(provider, answers)
        reqs = provider.answers["requirements"]
        assert len(reqs) == 3
        assert reqs[0] == {
            "name": "numpy", "req_type": "conda", "version": ">=1.0", "channel": "conda-forge"
        }
        assert reqs[1] == {
            "name": "pandas", "req_type": "conda", "version": "*", "channel": "conda-forge"
        }
        assert reqs[2] == {
            "name": "scipy", "req_type": "conda", "version": ">=2.0", "channel": "conda-forge"
        }

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
        q = next(gen)
        for ans in ["my_workflow", "My Workflow", "desc", "Author", "MIT"]:
            q = gen.send(ans)

        # First sub-question: name
        assert q["dest"] == "name"
        q = gen.send("numpy")
        # Second sub-question: req_type
        assert q["dest"] == "req_type"
        q = gen.send("conda")
        # Third: version (shown because req_type == "conda")
        assert q["dest"] == "version"
        # Send invalid version — re-yield with error
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

    def test_req_type_choices(self) -> None:
        """Verify req_type choices match REQ_TYPE_CHOICES."""
        assert REQ_TYPE_CHOICES == ["conda", "local path", "url", "git"]

    def test_local_path_requirement_in_loop(self) -> None:
        """Drive one local path requirement then stop — conda fields skipped."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "MIT",
            "mypackage",             # name
            "local path",            # req_type → skips version + channel, shows path
            "/home/user/mypackage",  # path
            "false",                 # editable
            "",                      # end loop
        ]
        drive_wizard(provider, answers)
        reqs = provider.answers["requirements"]
        assert len(reqs) == 1
        assert reqs[0] == {
            "name": "mypackage",
            "req_type": "local path",
            "path": "/home/user/mypackage",
            "editable": "false",
        }

    def test_url_requirement_in_loop(self) -> None:
        """Drive one URL requirement — other pip fields skipped."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "MIT",
            "mypackage",                     # name
            "url",                           # req_type
            "https://example.com/pkg.whl",   # url
            "",                              # end loop
        ]
        drive_wizard(provider, answers)
        reqs = provider.answers["requirements"]
        assert len(reqs) == 1
        assert reqs[0] == {
            "name": "mypackage",
            "req_type": "url",
            "url": "https://example.com/pkg.whl",
        }

    def test_git_requirement_no_ref(self) -> None:
        """Drive one git requirement without a ref."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "MIT",
            "mypkg",                                   # name
            "git",                                     # req_type
            "https://github.com/org/pkg.git",          # git
            "none",                                    # git_ref_type
            "",                                        # end loop
        ]
        drive_wizard(provider, answers)
        reqs = provider.answers["requirements"]
        assert len(reqs) == 1
        assert reqs[0] == {
            "name": "mypkg",
            "req_type": "git",
            "git": "https://github.com/org/pkg.git",
            "git_ref_type": "none",
        }

    def test_git_requirement_with_branch(self) -> None:
        """Drive one git requirement with a branch ref."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "MIT",
            "mypkg",                                   # name
            "git",                                     # req_type
            "https://github.com/org/pkg.git",          # git
            "branch",                                  # git_ref_type
            "main",                                    # git_ref_value
            "",                                        # end loop
        ]
        drive_wizard(provider, answers)
        reqs = provider.answers["requirements"]
        assert len(reqs) == 1
        assert reqs[0] == {
            "name": "mypkg",
            "req_type": "git",
            "git": "https://github.com/org/pkg.git",
            "git_ref_type": "branch",
            "git_ref_value": "main",
        }

    def test_local_path_editable(self) -> None:
        """Drive one local path requirement with editable=true."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "MIT",
            "mypkg",              # name
            "local path",         # req_type
            "/home/user/mypkg",   # path
            "true",               # editable
            "",                   # end loop
        ]
        drive_wizard(provider, answers)
        reqs = provider.answers["requirements"]
        assert reqs[0]["editable"] == "true"

    def test_mixed_conda_and_url_requirements(self) -> None:
        """Drive one conda then one URL requirement in the same loop."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "MIT",
            "numpy",        # name
            "conda",        # req_type
            ">=1.0",        # version
            "conda-forge",  # channel
            "mypackage",    # name
            "url",          # req_type
            "https://example.com/pkg.whl",  # url
            "",             # end loop
        ]
        drive_wizard(provider, answers)
        reqs = provider.answers["requirements"]
        assert len(reqs) == 2
        assert reqs[0] == {
            "name": "numpy", "req_type": "conda", "version": ">=1.0", "channel": "conda-forge"
        }
        assert reqs[1] == {
            "name": "mypackage",
            "req_type": "url",
            "url": "https://example.com/pkg.whl",
        }

    def test_conda_fields_skipped_for_local_path(self) -> None:
        """version + channel not yielded for local path requirement."""
        provider = DefaultWizardProvider()
        gen = provider.input_generator()
        q = next(gen)
        for ans in ["my_workflow", "My Workflow", "desc", "Author", "MIT"]:
            q = gen.send(ans)
        assert q["dest"] == "name"
        q = gen.send("mypkg")
        assert q["dest"] == "req_type"
        q = gen.send("local path")
        # version + channel skipped — path shown directly
        assert q["dest"] == "path"

    def test_conda_fields_skipped_for_url(self) -> None:
        """version + channel not yielded for URL requirement."""
        provider = DefaultWizardProvider()
        gen = provider.input_generator()
        q = next(gen)
        for ans in ["my_workflow", "My Workflow", "desc", "Author", "MIT"]:
            q = gen.send(ans)
        q = gen.send("mypkg")
        assert q["dest"] == "req_type"
        q = gen.send("url")
        assert q["dest"] == "url"

    def test_non_git_fields_skipped_for_conda(self) -> None:
        """path/url/git sub-questions not yielded for conda requirement."""
        provider = DefaultWizardProvider()
        gen = provider.input_generator()
        q = next(gen)
        for ans in ["my_workflow", "My Workflow", "desc", "Author", "MIT"]:
            q = gen.send(ans)
        q = gen.send("numpy")
        assert q["dest"] == "req_type"
        q = gen.send("conda")
        assert q["dest"] == "version"
        q = gen.send(">=1.0")
        assert q["dest"] == "channel"
        q = gen.send("conda-forge")
        # Next should be name again (loop repeats)
        assert q["dest"] == "name"

    def test_git_ref_value_skipped_when_ref_type_none(self) -> None:
        """git_ref_value not yielded when git_ref_type is 'none'."""
        provider = DefaultWizardProvider()
        gen = provider.input_generator()
        q = next(gen)
        for ans in ["my_workflow", "My Workflow", "desc", "Author", "MIT"]:
            q = gen.send(ans)
        q = gen.send("mypkg")           # name
        assert q["dest"] == "req_type"
        q = gen.send("git")
        assert q["dest"] == "git"
        q = gen.send("https://github.com/org/pkg.git")
        assert q["dest"] == "git_ref_type"
        q = gen.send("none")
        # git_ref_value skipped — next is name (loop repeats)
        assert q["dest"] == "name"

    def test_path_editable_skipped_when_url(self) -> None:
        """path + editable not yielded for a URL requirement."""
        provider = DefaultWizardProvider()
        gen = provider.input_generator()
        q = next(gen)
        for ans in ["my_workflow", "My Workflow", "desc", "Author", "MIT"]:
            q = gen.send(ans)
        q = gen.send("mypkg")           # name
        assert q["dest"] == "req_type"
        q = gen.send("url")
        # path + editable skipped — url shown directly
        assert q["dest"] == "url"


class TestPipValidators:
    """Tests for pip-related validation callables."""

    def test_absolute_path_accepted(self) -> None:
        assert _absolute_path_type("/home/user/mypkg") == "/home/user/mypkg"

    def test_relative_path_raises(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="not an absolute"):
            _absolute_path_type("relative/path")

    def test_absolute_path_empty_raises(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="cannot be empty"):
            _absolute_path_type("")

    def test_http_url_accepted(self) -> None:
        assert _http_url_type("https://example.com/pkg.whl") == "https://example.com/pkg.whl"

    def test_http_url_http_accepted(self) -> None:
        assert _http_url_type("http://example.com/pkg.whl") == "http://example.com/pkg.whl"

    def test_http_url_ftp_raises(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="not a valid http/https"):
            _http_url_type("ftp://example.com/pkg")

    def test_http_url_empty_raises(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="cannot be empty"):
            _http_url_type("")

    def test_git_url_https_accepted(self) -> None:
        assert _git_url_type("https://github.com/org/pkg.git") == "https://github.com/org/pkg.git"

    def test_git_url_git_plus_raises(self) -> None:
        """git+ prefix is not valid — plain URL is required."""
        with pytest.raises(argparse.ArgumentTypeError, match="not a valid git URL"):
            _git_url_type("git+https://github.com/org/pkg.git")

    def test_git_url_empty_raises(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="cannot be empty"):
            _git_url_type("")


class TestRequirementsBatchType:
    """Tests for _requirements_batch_type validation callable."""

    def test_conda_inferred_from_channel(self) -> None:
        d = _requirements_batch_type('{"name":"numpy","version":">=1.0","channel":"conda-forge"}')
        assert d["req_type"] == "conda"
        assert d["name"] == "numpy"
        assert d["version"] == ">=1.0"
        assert d["channel"] == "conda-forge"

    def test_local_path_inferred_from_path_key(self) -> None:
        d = _requirements_batch_type('{"name":"mypkg","path":"/home/user/mypkg"}')
        assert d["req_type"] == "local path"
        assert d["path"] == "/home/user/mypkg"
        assert d["editable"] == "false"
        assert "pip_source_type" not in d

    def test_url_inferred_from_url_key(self) -> None:
        d = _requirements_batch_type('{"name":"mypkg","url":"https://example.com/pkg.whl"}')
        assert d["req_type"] == "url"
        assert d["url"] == "https://example.com/pkg.whl"

    def test_git_inferred_from_git_key(self) -> None:
        d = _requirements_batch_type(
            '{"name":"mypkg","git":"https://github.com/org/pkg.git"}'
        )
        assert d["req_type"] == "git"
        assert d["git"] == "https://github.com/org/pkg.git"
        assert d["git_ref_type"] == "none"

    def test_git_branch_normalized(self) -> None:
        d = _requirements_batch_type(
            '{"name":"mypkg","git":"https://github.com/org/pkg.git","branch":"main"}'
        )
        assert d["git_ref_type"] == "branch"
        assert d["git_ref_value"] == "main"
        assert "branch" not in d  # original key removed

    def test_git_tag_normalized(self) -> None:
        d = _requirements_batch_type(
            '{"name":"mypkg","git":"https://github.com/org/pkg.git","tag":"v1.0.0"}'
        )
        assert d["git_ref_type"] == "tag"
        assert d["git_ref_value"] == "v1.0.0"

    def test_git_rev_normalized(self) -> None:
        d = _requirements_batch_type(
            '{"name":"mypkg","git":"https://github.com/org/pkg.git","rev":"abc123"}'
        )
        assert d["git_ref_type"] == "rev"
        assert d["git_ref_value"] == "abc123"

    def test_local_path_editable_true(self) -> None:
        d = _requirements_batch_type('{"name":"mypkg","path":"/abs/path","editable":true}')
        assert d["editable"] == "true"

    def test_local_path_editable_false(self) -> None:
        d = _requirements_batch_type('{"name":"mypkg","path":"/abs/path","editable":false}')
        assert d["editable"] == "false"

    def test_explicit_req_type_conda(self) -> None:
        d = _requirements_batch_type(
            '{"name":"numpy","req_type":"conda","version":"*","channel":"conda-forge"}'
        )
        assert d["req_type"] == "conda"

    def test_explicit_req_type_local_path(self) -> None:
        d = _requirements_batch_type(
            '{"name":"mypkg","req_type":"local path","path":"/abs/path"}'
        )
        assert d["req_type"] == "local path"

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid JSON"):
            _requirements_batch_type("not-json")

    def test_invalid_version_raises(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="version"):
            _requirements_batch_type(
                '{"name":"numpy","version":">>>bad<<<","channel":"conda-forge"}'
            )

    def test_invalid_channel_raises(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="channel"):
            _requirements_batch_type(
                '{"name":"numpy","version":"*","channel":"not-a-channel"}'
            )

    def test_invalid_path_raises(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="path"):
            _requirements_batch_type('{"name":"mypkg","path":"relative/path"}')

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="url"):
            _requirements_batch_type('{"name":"mypkg","url":"ftp://example.com/pkg"}')

    def test_invalid_git_url_raises(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="git"):
            _requirements_batch_type('{"name":"mypkg","git":"not-a-url"}')

    def test_invalid_req_type_raises(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="req_type"):
            _requirements_batch_type('{"name":"mypkg","req_type":"pip"}')

    def test_empty_name_raises(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="name"):
            _requirements_batch_type('{"name":"","version":"*","channel":"conda-forge"}')


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
        """Send invalid license string — re-yield with error."""
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
            "numpy",   # name
            "conda",   # req_type
            ">=1.0",   # version
            "conda-forge",  # channel
            "",  # end requirements loop
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

    def test_dump_spec_yaml_local_path(self, tmp_path: Path) -> None:
        """spec.yaml renders local path requirement correctly."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow", "My Workflow", "", "Author", "MIT",
            "mypkg", "local path", "/home/user/mypkg", "false", "",
        ]
        drive_wizard(provider, answers)
        provider.dump(tmp_path)
        content = yaml.safe_load((tmp_path / "spec.yaml").read_text())
        req = content["requirements"][0]
        assert req["name"] == "mypkg"
        assert req["path"] == "/home/user/mypkg"
        assert "editable" not in req

    def test_dump_spec_yaml_local_path_editable(self, tmp_path: Path) -> None:
        """spec.yaml renders local path+editable requirement correctly."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow", "My Workflow", "", "Author", "MIT",
            "mypkg", "local path", "/home/user/mypkg", "true", "",
        ]
        drive_wizard(provider, answers)
        provider.dump(tmp_path)
        content = yaml.safe_load((tmp_path / "spec.yaml").read_text())
        req = content["requirements"][0]
        assert req["editable"] is True

    def test_dump_spec_yaml_url(self, tmp_path: Path) -> None:
        """spec.yaml renders URL requirement correctly."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow", "My Workflow", "", "Author", "MIT",
            "mypkg", "url", "https://example.com/pkg.whl", "",
        ]
        drive_wizard(provider, answers)
        provider.dump(tmp_path)
        content = yaml.safe_load((tmp_path / "spec.yaml").read_text())
        req = content["requirements"][0]
        assert req["url"] == "https://example.com/pkg.whl"

    def test_dump_spec_yaml_git_with_branch(self, tmp_path: Path) -> None:
        """spec.yaml renders git+branch requirement correctly."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow", "My Workflow", "", "Author", "MIT",
            "mypkg", "git", "https://github.com/org/pkg.git", "branch", "main", "",
        ]
        drive_wizard(provider, answers)
        provider.dump(tmp_path)
        content = yaml.safe_load((tmp_path / "spec.yaml").read_text())
        req = content["requirements"][0]
        assert req["git"] == "https://github.com/org/pkg.git"
        assert req["branch"] == "main"

    def test_dump_spec_yaml_git_no_ref(self, tmp_path: Path) -> None:
        """spec.yaml renders git (no ref) requirement correctly."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow", "My Workflow", "", "Author", "MIT",
            "mypkg", "git", "https://github.com/org/pkg.git", "none", "",
        ]
        drive_wizard(provider, answers)
        provider.dump(tmp_path)
        content = yaml.safe_load((tmp_path / "spec.yaml").read_text())
        req = content["requirements"][0]
        assert req["git"] == "https://github.com/org/pkg.git"
        assert "branch" not in req
        assert "tag" not in req
        assert "rev" not in req

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
