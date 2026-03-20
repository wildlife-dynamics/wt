"""Tests for CLI functionality."""

import argparse
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wt_compiler.cli import main, _write_init_artifacts
from wt_compiler.wizard.abstract import AbstractWizardProvider

# ---------------------------------------------------------------------------
# Mock provider module factory (used by register-provider / list-providers /
# init-with-provider tests).  Lazy imports in the handlers are intercepted by
# pre-inserting a fake module into sys.modules via patch.dict.
# ---------------------------------------------------------------------------


def make_mock_providers(**overrides: object) -> types.ModuleType:
    """Build a fake wt_compiler.providers module for use with patch.dict.

    Args:
        **overrides: Attribute overrides on the fake module.

    Returns:
        A ``types.ModuleType`` with default mocks and any requested overrides.
    """
    m = types.ModuleType("wt_compiler.wizard.providers")
    m.get_available_providers = MagicMock(return_value=[])  # type: ignore[attr-defined]
    m.load_provider_class = MagicMock()  # type: ignore[attr-defined]
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


class TestMainParser:
    """Tests for main CLI parser."""

    def test_help_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that --help displays usage information."""
        with patch.object(sys, "argv", ["wt-compiler", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "wt-compiler" in captured.out
        assert "compile" in captured.out

    def test_compile_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that compile --help displays compile-specific help."""
        with patch.object(sys, "argv", ["wt-compiler", "compile", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "--spec" in captured.out
        assert "--clobber" in captured.out
        assert "--update" in captured.out
        assert "--install" in captured.out

    def test_no_command_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that missing command shows error."""
        with patch.object(sys, "argv", ["wt-compiler"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        # argparse exits with code 2 for argument errors
        assert exc_info.value.code == 2

    def test_compile_missing_spec_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that compile without --spec shows error."""
        with patch.object(sys, "argv", ["wt-compiler", "compile"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "--spec" in captured.err


class TestMakeQuestionaryValidator:
    """Unit tests for _make_questionary_validator()."""

    def test_returns_true_on_valid_input(self) -> None:
        """Valid input returns True."""
        from wt_compiler.cli import _make_questionary_validator
        from wt_compiler.wizard.default import workflow_id_type

        validator = _make_questionary_validator(workflow_id_type)
        assert validator("my_workflow") is True

    def test_returns_error_string_on_invalid_input(self) -> None:
        """Invalid input returns an error string (not raises)."""
        from wt_compiler.cli import _make_questionary_validator
        from wt_compiler.wizard.default import workflow_id_type

        validator = _make_questionary_validator(workflow_id_type)
        result = validator("123bad")
        assert isinstance(result, str)
        assert result  # non-empty error message

    def test_returns_true_for_non_empty_str(self) -> None:
        """non_empty_str validator returns True for valid input."""
        from wt_compiler.cli import _make_questionary_validator
        from wt_compiler.wizard.default import non_empty_str

        validator = _make_questionary_validator(non_empty_str)
        assert validator("Author Name") is True

    def test_returns_error_string_for_empty_str(self) -> None:
        """non_empty_str validator returns error string for whitespace-only input."""
        from wt_compiler.cli import _make_questionary_validator
        from wt_compiler.wizard.default import non_empty_str

        validator = _make_questionary_validator(non_empty_str)
        result = validator("   ")
        assert isinstance(result, str)
        assert result  # non-empty error message


class TestCompileCommand:
    """Tests for the compile command."""

    def test_spec_file_not_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test error when spec file doesn't exist."""
        with patch.object(
            sys, "argv", ["wt-compiler", "compile", "--spec", "/nonexistent/spec.yaml"]
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: Spec file not found" in captured.err

    def test_spec_path_is_directory(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test error when spec path is a directory."""
        with patch.object(sys, "argv", ["wt-compiler", "compile", "--spec", str(tmp_path)]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: Spec path is not a file" in captured.err

    def test_compile_success(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """Test successful compilation with mocked compile_workflow_from_yaml."""
        # Create a dummy spec file
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        # Create mock artifacts
        mock_artifacts = MagicMock()
        mock_artifacts.release_dir = tmp_path / "test-workflow"

        with patch.object(sys, "argv", ["wt-compiler", "compile", "--spec", str(spec_file)]):
            with patch(
                "wt_compiler.cli.compile_workflow_from_yaml", return_value=mock_artifacts
            ) as mock_compile:
                main()

        mock_compile.assert_called_once_with(
            str(spec_file.resolve()), progress=True, pkg_name_prefix="wt", results_env_var="WT_RESULTS"
        )
        mock_artifacts.dump.assert_called_once_with(clobber=False, update=False)

        captured = capsys.readouterr()
        assert "Compiled workflow to:" in captured.out

    def test_compile_with_clobber(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """Test compilation with --clobber flag."""
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        mock_artifacts = MagicMock()
        mock_artifacts.release_dir = tmp_path / "test-workflow"

        with patch.object(
            sys, "argv", ["wt-compiler", "compile", "--spec", str(spec_file), "--clobber"]
        ):
            with patch("wt_compiler.cli.compile_workflow_from_yaml", return_value=mock_artifacts):
                main()

        mock_artifacts.dump.assert_called_once_with(clobber=True, update=False)

    def test_compile_with_update(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """Test compilation with --update flag."""
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        mock_artifacts = MagicMock()
        mock_artifacts.release_dir = tmp_path / "test-workflow"

        with patch.object(
            sys,
            "argv",
            ["wt-compiler", "compile", "--spec", str(spec_file), "--clobber", "--update"],
        ):
            with patch("wt_compiler.cli.compile_workflow_from_yaml", return_value=mock_artifacts):
                main()

        mock_artifacts.dump.assert_called_once_with(clobber=True, update=True)

    def test_compile_file_exists_error(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test error handling when output directory exists without --clobber."""
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        mock_artifacts = MagicMock()
        mock_artifacts.dump.side_effect = FileExistsError("Path 'test-workflow' already exists.")

        with patch.object(sys, "argv", ["wt-compiler", "compile", "--spec", str(spec_file)]):
            with patch("wt_compiler.cli.compile_workflow_from_yaml", return_value=mock_artifacts):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err
        assert "--clobber" in captured.err

    def test_compile_general_error(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test error handling for general exceptions during compilation."""
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        with patch.object(sys, "argv", ["wt-compiler", "compile", "--spec", str(spec_file)]):
            with patch(
                "wt_compiler.cli.compile_workflow_from_yaml",
                side_effect=ValueError("Invalid spec format"),
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: Invalid spec format" in captured.err

    def test_compile_with_install(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test that --install calls artifacts.install() after dump."""
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        mock_artifacts = MagicMock()
        mock_artifacts.release_dir = tmp_path / "test-workflow"

        with patch.object(
            sys,
            "argv",
            ["wt-compiler", "compile", "--spec", str(spec_file), "--install"],
        ):
            with patch("wt_compiler.cli.compile_workflow_from_yaml", return_value=mock_artifacts):
                main()

        mock_artifacts.dump.assert_called_once_with(clobber=False, update=False)
        mock_artifacts.install.assert_called_once()
        mock_artifacts.update.assert_not_called()

    def test_compile_with_clobber_and_update_calls_update(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test that --clobber --update calls artifacts.update() after dump."""
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        mock_artifacts = MagicMock()
        mock_artifacts.release_dir = tmp_path / "test-workflow"

        with patch.object(
            sys,
            "argv",
            ["wt-compiler", "compile", "--spec", str(spec_file), "--clobber", "--update"],
        ):
            with patch("wt_compiler.cli.compile_workflow_from_yaml", return_value=mock_artifacts):
                main()

        mock_artifacts.dump.assert_called_once_with(clobber=True, update=True)
        mock_artifacts.update.assert_called_once()
        mock_artifacts.install.assert_not_called()

    def test_compile_update_without_clobber_error(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test that --update without --clobber exits with error."""
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        with patch.object(
            sys,
            "argv",
            ["wt-compiler", "compile", "--spec", str(spec_file), "--update"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "--update is only valid with --clobber and without --install" in captured.err

    def test_compile_update_with_install_error(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test that --update with --install exits with error."""
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        with patch.object(
            sys,
            "argv",
            [
                "wt-compiler",
                "compile",
                "--spec",
                str(spec_file),
                "--clobber",
                "--update",
                "--install",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "--update is only valid with --clobber and without --install" in captured.err


class TestInitCommand:
    """Tests for the init subcommand."""

    def test_init_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that init --help shows expected flags."""
        with patch.object(sys, "argv", ["wt-compiler", "init", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "--output-dir" in captured.out
        assert "--clobber" in captured.out
        assert "--workflow-id" in captured.out
        assert "--workflow-name" in captured.out
        assert "--workflow-description" in captured.out
        assert "--author-name" in captured.out
        assert "--license-type" in captured.out
        assert "--requirements" in captured.out

    def test_init_in_help_listing(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that 'init' appears in the top-level help."""
        with patch.object(sys, "argv", ["wt-compiler", "--help"]):
            with pytest.raises(SystemExit):
                main()
        captured = capsys.readouterr()
        assert "init" in captured.out

    def test_init_batch_mode_success(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Batch mode: all required flags → dump() called with correct workdir."""
        with patch.object(
            sys,
            "argv",
            [
                "wt-compiler", "init",
                "--no-interactive",
                "--workflow-id", "my_workflow",
                "--workflow-name", "My Workflow",
                "--author-name", "Author",
                "--output-dir", str(tmp_path),
            ],
        ):
            with patch("wt_compiler.wizard.abstract.AbstractWizardProvider.dump") as mock_dump:
                with patch("builtins.input") as mock_input:
                    main()

        mock_dump.assert_called_once()
        mock_input.assert_not_called()
        assert mock_dump.call_args[0][0] == tmp_path / "my_workflow"
        assert "Initialized workflow project at:" in capsys.readouterr().out

    def test_init_batch_mode_sets_answers(self, tmp_path: Path) -> None:
        """Batch mode: provider._answers populated correctly from flags."""
        from wt_compiler.wizard import DefaultWizardProvider

        captured_provider: list[DefaultWizardProvider] = []

        def capture_dump(self: DefaultWizardProvider, workdir: Path) -> None:
            captured_provider.append(self)

        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_wf",
            "--workflow-name", "My Workflow",
            "--workflow-description", "A desc",
            "--author-name", "Author",
            "--license-type", "MIT",
            "--output-dir", str(tmp_path),
        ]):
            with patch("wt_compiler.wizard.abstract.AbstractWizardProvider.dump", capture_dump):
                main()

        assert len(captured_provider) == 1
        p = captured_provider[0]
        assert p.answers["workflow_id"] == "my_wf"
        assert p.answers["workflow_description"] == "A desc"
        assert p.answers["license_type"] == "MIT"
        assert p.answers["requirements"] == []

    def test_init_batch_mode_defaults(self, tmp_path: Path) -> None:
        """Batch mode: omitted optional flags use correct defaults."""
        from wt_compiler.wizard import DefaultWizardProvider

        captured_provider: list[DefaultWizardProvider] = []

        def capture_dump(self: DefaultWizardProvider, workdir: Path) -> None:
            captured_provider.append(self)

        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_wf",
            "--workflow-name", "My Workflow",
            "--author-name", "Author",
            "--output-dir", str(tmp_path),
        ]):
            with patch("wt_compiler.wizard.abstract.AbstractWizardProvider.dump", capture_dump):
                main()

        p = captured_provider[0]
        assert p.answers["workflow_description"] == ""
        assert p.answers["license_type"] == "BSD-3-Clause"

    def test_init_batch_mode_with_requirements(self, tmp_path: Path) -> None:
        """Batch mode: --requirements flags are expanded through the loop generator."""
        from wt_compiler.wizard import DefaultWizardProvider

        captured_provider: list[DefaultWizardProvider] = []

        def capture_dump(self: DefaultWizardProvider, workdir: Path) -> None:
            captured_provider.append(self)

        with patch.object(
            sys,
            "argv",
            [
                "wt-compiler", "init",
                "--no-interactive",
                "--workflow-id", "my_wf",
                "--workflow-name", "My Workflow",
                "--author-name", "Author",
                "--requirements", '{"name":"pandas","version":">=2.0","channel":"conda-forge"}',
                "--requirements", '{"name":"numpy","version":"*","channel":"conda-forge"}',
                "--output-dir", str(tmp_path),
            ],
        ):
            with patch("wt_compiler.wizard.abstract.AbstractWizardProvider.dump", capture_dump):
                main()

        reqs = captured_provider[0].answers["requirements"]
        assert len(reqs) == 2
        assert reqs[0] == {"name": "pandas", "req_type": "conda", "version": ">=2.0", "channel": "conda-forge"}
        assert reqs[1] == {"name": "numpy", "req_type": "conda", "version": "*", "channel": "conda-forge"}

    def test_init_batch_mode_no_input_calls(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Batch mode never calls input() regardless of which flags are supplied."""
        with patch.object(
            sys,
            "argv",
            [
                "wt-compiler", "init",
                "--no-interactive",
                "--workflow-id", "my_wf",
                "--workflow-name", "My Workflow",
                "--workflow-description", "desc",
                "--author-name", "Author",
                "--license-type", "MIT",
                "--requirements", '{"name":"pkg","version":"*","channel":"conda-forge"}',
                "--output-dir", str(tmp_path),
            ],
        ):
            with patch("wt_compiler.wizard.abstract.AbstractWizardProvider.dump"):
                with patch("builtins.input") as mock_input:
                    with patch("questionary.text") as mock_text:
                        with patch("questionary.select") as mock_select:
                            with patch("questionary.confirm") as mock_confirm:
                                main()

        mock_input.assert_not_called()
        mock_text.assert_not_called()
        mock_select.assert_not_called()
        mock_confirm.assert_not_called()

    def test_init_interactive_mode(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Interactive mode: questionary drives wizard, dump() called with correct workdir."""
        # questionary.confirm for loop: first True (add one conda req), second False (stop)
        confirm_mock = MagicMock()
        confirm_mock.return_value.ask.side_effect = [True, False]
        # questionary.text: workflow_id, workflow_name, description, author_name, name, version
        text_mock = MagicMock()
        text_mock.return_value.ask.side_effect = [
            "my_workflow", "My Workflow", "", "Author",
            "numpy", "*",
        ]
        # questionary.select: license_type, req_type (conda), channel
        select_mock = MagicMock()
        select_mock.return_value.ask.side_effect = ["MIT", "conda", "conda-forge"]

        mock_providers = make_mock_providers()
        with patch("wt_compiler.cli.wt_providers", mock_providers):
            with patch.object(sys, "argv", ["wt-compiler", "init", "--output-dir", str(tmp_path)]):
                with patch("questionary.text", text_mock):
                    with patch("questionary.select", select_mock):
                        with patch("questionary.confirm", confirm_mock):
                            with patch(
                                "wt_compiler.wizard.abstract.AbstractWizardProvider.dump"
                            ) as mock_dump:
                                main()

        mock_dump.assert_called_once()
        assert mock_dump.call_args[0][0] == tmp_path / "my_workflow"

    def test_init_interactive_select_for_choice_fields(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Choice fields use questionary.select, not questionary.text."""
        confirm_mock = MagicMock()
        confirm_mock.return_value.ask.side_effect = [True, False]
        text_mock = MagicMock()
        text_mock.return_value.ask.side_effect = [
            "my_workflow", "My Workflow", "", "Author",
            "numpy", "*",
        ]
        select_mock = MagicMock()
        select_mock.return_value.ask.side_effect = ["MIT", "conda", "conda-forge"]

        mock_providers = make_mock_providers()
        with patch("wt_compiler.cli.wt_providers", mock_providers):
            with patch.object(sys, "argv", ["wt-compiler", "init", "--output-dir", str(tmp_path)]):
                with patch("questionary.text", text_mock):
                    with patch("questionary.select", select_mock):
                        with patch("questionary.confirm", confirm_mock):
                            with patch("wt_compiler.wizard.abstract.AbstractWizardProvider.dump"):
                                main()

        # questionary.select called for license_type, req_type (conda), channel
        assert select_mock.call_count == 3
        # questionary.text called for: workflow_id, workflow_name, description,
        # author_name, name, version
        assert text_mock.call_count == 6

    def test_init_existing_dir_error(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Error when workdir exists and --clobber not set."""
        (tmp_path / "my_workflow").mkdir()

        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_workflow",
            "--workflow-name", "My Workflow",
            "--author-name", "Author",
            "--output-dir", str(tmp_path),
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "already exists" in captured.err
        assert "--clobber" in captured.err

    def test_init_clobber_existing_dir(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """--clobber allows scaffolding into existing directory."""
        (tmp_path / "my_workflow").mkdir()

        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_workflow",
            "--workflow-name", "My Workflow",
            "--author-name", "Author",
            "--output-dir", str(tmp_path),
            "--clobber",
        ]):
            with patch("wt_compiler.wizard.abstract.AbstractWizardProvider.dump") as mock_dump:
                main()

        mock_dump.assert_called_once()

    def test_init_output_dir_defaults_to_cwd(self, tmp_path: Path) -> None:
        """Without --output-dir, workdir is Path.cwd() / workflow_id."""
        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_workflow",
            "--workflow-name", "My Workflow",
            "--author-name", "Author",
        ]):
            with patch("wt_compiler.wizard.abstract.AbstractWizardProvider.dump") as mock_dump:
                with patch("pathlib.Path.cwd", return_value=tmp_path):
                    with patch("pathlib.Path.exists", return_value=False):
                        main()

        assert mock_dump.call_args[0][0] == tmp_path / "my_workflow"

    def test_init_dump_error(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Generic exception from dump() exits 1 with error message on stderr."""
        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_workflow",
            "--workflow-name", "My Workflow",
            "--author-name", "Author",
            "--output-dir", str(tmp_path),
        ]):
            with patch(
                "wt_compiler.wizard.abstract.AbstractWizardProvider.dump",
                side_effect=RuntimeError("template error"),
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 1
        assert "template error" in capsys.readouterr().err

    def test_init_no_interactive_missing_required_flags(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """--no-interactive without required flags exits 1 with clear error."""
        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_workflow",
            # missing --workflow-name and --author-name
            "--output-dir", str(tmp_path),
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "--no-interactive requires" in captured.err
        assert "--workflow-name" in captured.err
        assert "--author-name" in captured.err

    def test_init_batch_invalid_workflow_id(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--workflow-id with invalid value is rejected by argparse (exit 2)."""
        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "123bad",
            "--workflow-name", "My Workflow",
            "--author-name", "Author",
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2

    def test_init_batch_invalid_workflow_name(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--workflow-name with whitespace-only value is rejected by argparse (exit 2)."""
        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_workflow",
            "--workflow-name", "   ",
            "--author-name", "Author",
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2

    def test_init_batch_invalid_license_type(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--license-type with value outside choices is rejected by argparse (exit 2)."""
        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_workflow",
            "--workflow-name", "My Workflow",
            "--author-name", "Author",
            "--license-type", "INVALID",
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2

    def test_init_batch_invalid_requirement_name(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--requirements with empty package name is rejected by argparse (exit 2)."""
        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_workflow",
            "--workflow-name", "My Workflow",
            "--author-name", "Author",
            "--requirements", '{"name":"","version":"*","channel":"conda-forge"}',
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2

    def test_init_batch_invalid_requirement_version(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--requirements with invalid version spec is rejected by argparse (exit 2)."""
        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_workflow",
            "--workflow-name", "My Workflow",
            "--author-name", "Author",
            "--requirements", '{"name":"numpy","version":">>>bad<<<","channel":"conda-forge"}',
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2

    def test_init_batch_invalid_requirement_version_multiple_requirements(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--requirements with invalid version spec is rejected by argparse (exit 2)."""
        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_workflow",
            "--workflow-name", "My Workflow",
            "--author-name", "Author",
            "--requirements", '{"name":"numpy","version":"*","channel":"conda-forge"}',
            "--requirements", '{"name":"geopandas","version":">>>bad<<<","channel":"conda-forge"}',
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2

    def test_init_batch_local_path_requirement(self, tmp_path: Path) -> None:
        """--requirements with local path stored correctly in answers."""
        from wt_compiler.wizard import DefaultWizardProvider

        captured_provider: list[DefaultWizardProvider] = []

        def capture_dump(self: DefaultWizardProvider, workdir: Path) -> None:
            captured_provider.append(self)

        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_wf",
            "--workflow-name", "My Workflow",
            "--author-name", "Author",
            "--requirements", '{"name":"mypackage","path":"/home/user/mypackage"}',
            "--output-dir", str(tmp_path),
        ]):
            with patch("wt_compiler.wizard.abstract.AbstractWizardProvider.dump", capture_dump):
                main()

        reqs = captured_provider[0].answers["requirements"]
        assert len(reqs) == 1
        assert reqs[0] == {
            "name": "mypackage",
            "req_type": "local path",
            "path": "/home/user/mypackage",
            "editable": "false",
        }

    def test_init_batch_git_requirement(self, tmp_path: Path) -> None:
        """--requirements with git+branch stored correctly in answers."""
        from wt_compiler.wizard import DefaultWizardProvider

        captured_provider: list[DefaultWizardProvider] = []

        def capture_dump(self: DefaultWizardProvider, workdir: Path) -> None:
            captured_provider.append(self)

        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_wf",
            "--workflow-name", "My Workflow",
            "--author-name", "Author",
            "--requirements", (
                '{"name":"mypkg","git":"https://github.com/org/pkg.git","branch":"main"}'
            ),
            "--output-dir", str(tmp_path),
        ]):
            with patch("wt_compiler.wizard.abstract.AbstractWizardProvider.dump", capture_dump):
                main()

        reqs = captured_provider[0].answers["requirements"]
        assert len(reqs) == 1
        assert reqs[0] == {
            "name": "mypkg",
            "req_type": "git",
            "git": "https://github.com/org/pkg.git",
            "git_ref_type": "branch",
            "git_ref_value": "main",
        }

    def test_init_batch_invalid_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--requirements with relative path is rejected by argparse (exit 2)."""
        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_workflow",
            "--workflow-name", "My Workflow",
            "--author-name", "Author",
            "--requirements", '{"name":"mypkg","path":"relative/path"}',
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2

    def test_init_batch_invalid_url(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--requirements with invalid URL is rejected by argparse (exit 2)."""
        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--no-interactive",
            "--workflow-id", "my_workflow",
            "--workflow-name", "My Workflow",
            "--author-name", "Author",
            "--requirements", '{"name":"mypkg","url":"ftp://example.com/pkg"}',
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2

class TestModuleEntryPoint:
    """Tests for python -m wt_compiler entry point."""

    def test_main_module_import(self) -> None:
        """Test that __main__.py can be imported."""
        import wt_compiler.__main__

        assert hasattr(wt_compiler.__main__, "main")


# ---------------------------------------------------------------------------
# TestInitCommandWithProvider
# ---------------------------------------------------------------------------


class _MinimalProvider(AbstractWizardProvider):
    """Minimal provider for testing: yields only workflow_id."""

    def get_questions(self) -> list:  # type: ignore[override]
        return [{"dest": "workflow_id", "argparse": {"help": "ID", "type": str}, "wizard": {}}]


class TestInitCommandWithProvider:
    """Tests for wt-compiler init <PROVIDER> path."""

    def test_init_help_shows_provider_flag(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """init --help shows --provider flag."""
        with patch.object(sys, "argv", ["wt-compiler", "init", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        assert "--provider" in capsys.readouterr().out

    def test_init_with_provider_interactive(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Custom provider: interactive path calls dump with correct workdir."""
        mock_providers = make_mock_providers(
            load_provider_class=MagicMock(return_value=_MinimalProvider)
        )
        text_mock = MagicMock()
        text_mock.return_value.ask.side_effect = ["my_wf"]
        confirm_mock = MagicMock()
        confirm_mock.return_value.ask.return_value = False

        with patch("wt_compiler.cli.wt_providers", mock_providers):
            with patch.object(
                sys,
                "argv",
                ["wt-compiler", "init", "--provider", "my-provider", "--output-dir", str(tmp_path)],
            ):
                with patch("questionary.text", text_mock):
                    with patch("questionary.confirm", confirm_mock):
                        with patch(
                            "wt_compiler.wizard.abstract.AbstractWizardProvider.dump"
                        ) as mock_dump:
                            main()

        mock_dump.assert_called_once_with(tmp_path / "my_wf")

    def test_init_with_provider_no_interactive_success(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """--no-interactive with all required flags succeeds for a custom provider."""
        mock_providers = make_mock_providers(
            load_provider_class=MagicMock(return_value=_MinimalProvider)
        )
        with patch("wt_compiler.cli.wt_providers", mock_providers):
            with patch.object(
                sys,
                "argv",
                [
                    "wt-compiler",
                    "init",
                    "--provider",
                    "my-provider",
                    "--no-interactive",
                    "--workflow-id",
                    "my_wf",
                    "--output-dir",
                    str(tmp_path),
                ],
            ):
                with patch(
                    "wt_compiler.wizard.abstract.AbstractWizardProvider.dump"
                ) as mock_dump:
                    main()
        mock_dump.assert_called_once_with(tmp_path / "my_wf")

    def test_init_with_provider_no_interactive_missing_flags(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--no-interactive without required flags exits 1 with '--no-interactive requires'."""
        mock_providers = make_mock_providers(
            load_provider_class=MagicMock(return_value=_MinimalProvider)
        )
        with patch("wt_compiler.cli.wt_providers", mock_providers):
            with patch.object(
                sys,
                "argv",
                ["wt-compiler", "init", "--provider", "my-provider", "--no-interactive"],
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()
        assert exc_info.value.code == 1
        assert "--no-interactive requires" in capsys.readouterr().err

    def test_init_with_unknown_provider_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Unknown provider name → exit 1 with 'not registered' on stderr."""
        mock_providers = make_mock_providers(
            load_provider_class=MagicMock(side_effect=ValueError("not registered"))
        )
        with patch("wt_compiler.cli.wt_providers", mock_providers):
            with patch.object(
                sys, "argv", ["wt-compiler", "init", "--provider", "unknown-provider"]
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()
        assert exc_info.value.code == 1
        assert "not registered" in capsys.readouterr().err

    def test_init_with_invalid_provider_class_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Invalid provider class → exit 1 with 'not a subclass' on stderr."""
        mock_providers = make_mock_providers(
            load_provider_class=MagicMock(side_effect=TypeError("not a subclass"))
        )
        with patch("wt_compiler.cli.wt_providers", mock_providers):
            with patch.object(
                sys, "argv", ["wt-compiler", "init", "--provider", "bad-provider"]
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()
        assert exc_info.value.code == 1
        assert "not a subclass" in capsys.readouterr().err

    def test_init_with_provider_clobber(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """--clobber allows overwriting an existing workdir when using custom provider."""
        (tmp_path / "my_wf").mkdir()
        mock_providers = make_mock_providers(
            load_provider_class=MagicMock(return_value=_MinimalProvider)
        )
        text_mock = MagicMock()
        text_mock.return_value.ask.side_effect = ["my_wf"]
        confirm_mock = MagicMock()
        confirm_mock.return_value.ask.return_value = False

        with patch("wt_compiler.cli.wt_providers", mock_providers):
            with patch.object(
                sys,
                "argv",
                [
                    "wt-compiler",
                    "init",
                    "--provider",
                    "my-provider",
                    "--output-dir",
                    str(tmp_path),
                    "--clobber",
                ],
            ):
                with patch("questionary.text", text_mock):
                    with patch("questionary.confirm", confirm_mock):
                        with patch(
                            "wt_compiler.wizard.abstract.AbstractWizardProvider.dump"
                        ) as mock_dump:
                            main()

        mock_dump.assert_called_once()


# ---------------------------------------------------------------------------
# TestInitProviderSelection
# ---------------------------------------------------------------------------


class TestInitProviderSelection:
    """Tests for the interactive provider selection prompt in wt-compiler init."""

    def test_shows_selector_and_uses_selected_provider(
        self, tmp_path: Path
    ) -> None:
        """Shows selector when providers are registered; selected provider is loaded."""
        mock_providers = make_mock_providers(
            get_available_providers=MagicMock(return_value=[{"name": "my-provider", "package": "pkg"}]),
            load_provider_class=MagicMock(return_value=_MinimalProvider),
        )
        select_mock = MagicMock()
        select_mock.return_value.ask.return_value = "my-provider"
        text_mock = MagicMock()
        text_mock.return_value.ask.side_effect = ["my_wf"]
        confirm_mock = MagicMock()
        confirm_mock.return_value.ask.return_value = False

        with patch("wt_compiler.cli.wt_providers", mock_providers):
            with patch.object(
                sys, "argv", ["wt-compiler", "init", "--output-dir", str(tmp_path)]
            ):
                with patch("questionary.select", select_mock):
                    with patch("questionary.text", text_mock):
                        with patch("questionary.confirm", confirm_mock):
                            with patch(
                                "wt_compiler.wizard.abstract.AbstractWizardProvider.dump"
                            ):
                                main()

        select_mock.assert_called_once()
        mock_providers.load_provider_class.assert_called_once_with("my-provider")

    def test_default_selection_uses_default_provider(
        self, tmp_path: Path
    ) -> None:
        """Selecting 'default' does not call load_provider_class."""
        mock_providers = make_mock_providers(
            get_available_providers=MagicMock(return_value=[{"name": "my-provider", "package": "pkg"}]),
            load_provider_class=MagicMock(return_value=_MinimalProvider),
        )
        select_mock = MagicMock()
        select_mock.return_value.ask.return_value = "default"
        text_mock = MagicMock()
        text_mock.return_value.ask.side_effect = ["my_wf", "My Workflow", "Author"]
        confirm_mock = MagicMock()
        confirm_mock.return_value.ask.return_value = False

        with patch("wt_compiler.cli.wt_providers", mock_providers):
            with patch.object(
                sys, "argv", ["wt-compiler", "init", "--output-dir", str(tmp_path)]
            ):
                with patch("questionary.select", select_mock):
                    with patch("questionary.text", text_mock):
                        with patch("questionary.confirm", confirm_mock):
                            with patch(
                                "wt_compiler.wizard.abstract.AbstractWizardProvider.dump"
                            ):
                                main()

        mock_providers.load_provider_class.assert_not_called()

    def test_ctrl_c_on_selector_exits_1(self) -> None:
        """Ctrl+C on selector (ask() returns None) exits with code 1."""
        mock_providers = make_mock_providers(
            get_available_providers=MagicMock(return_value=[{"name": "my-provider", "package": "pkg"}]),
        )
        select_mock = MagicMock()
        select_mock.return_value.ask.return_value = None

        with patch("wt_compiler.cli.wt_providers", mock_providers):
            with patch.object(sys, "argv", ["wt-compiler", "init"]):
                with patch("questionary.select", select_mock):
                    with pytest.raises(SystemExit) as exc_info:
                        main()

        assert exc_info.value.code == 1

    def test_no_interactive_skips_selector(self, tmp_path: Path) -> None:
        """--no-interactive skips the provider selection prompt."""
        mock_providers = make_mock_providers(
            get_available_providers=MagicMock(return_value=[{"name": "my-provider", "package": "pkg"}]),
            load_provider_class=MagicMock(return_value=_MinimalProvider),
        )
        select_mock = MagicMock()

        with patch("wt_compiler.cli.wt_providers", mock_providers):
            with patch.object(
                sys,
                "argv",
                [
                    "wt-compiler",
                    "init",
                    "--no-interactive",
                    "--workflow-id",
                    "my_wf",
                    "--workflow-name",
                    "My Workflow",
                    "--author-name",
                    "Author",
                    "--output-dir",
                    str(tmp_path),
                ],
            ):
                with patch("questionary.select", select_mock):
                    with patch(
                        "wt_compiler.wizard.abstract.AbstractWizardProvider.dump"
                    ):
                        main()

        select_mock.assert_not_called()

    def test_no_registered_providers_skips_selector(self, tmp_path: Path) -> None:
        """When no providers are registered, selector is not shown."""
        mock_providers = make_mock_providers(
            get_available_providers=MagicMock(return_value=[]),
        )
        select_mock = MagicMock()
        text_mock = MagicMock()
        text_mock.return_value.ask.side_effect = ["my_wf", "My Workflow", "Author"]
        confirm_mock = MagicMock()
        confirm_mock.return_value.ask.return_value = False

        with patch("wt_compiler.cli.wt_providers", mock_providers):
            with patch.object(
                sys, "argv", ["wt-compiler", "init", "--output-dir", str(tmp_path)]
            ):
                with patch("questionary.select", select_mock):
                    with patch("questionary.text", text_mock):
                        with patch("questionary.confirm", confirm_mock):
                            with patch(
                                "wt_compiler.wizard.abstract.AbstractWizardProvider.dump"
                            ):
                                main()

        select_mock.assert_not_called()

    def test_help_skips_selector(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--help skips the provider selection prompt."""
        mock_providers = make_mock_providers(
            get_available_providers=MagicMock(return_value=[{"name": "my-provider", "package": "pkg"}]),
        )
        select_mock = MagicMock()

        with patch("wt_compiler.cli.wt_providers", mock_providers):
            with patch.object(sys, "argv", ["wt-compiler", "init", "--help"]):
                with patch("questionary.select", select_mock):
                    with pytest.raises(SystemExit) as exc_info:
                        main()

        assert exc_info.value.code == 0
        select_mock.assert_not_called()


# ---------------------------------------------------------------------------
# TestFinalizeInit
# ---------------------------------------------------------------------------


class TestFinalizeInit:
    """Tests for _write_init_artifacts() path-traversal guards (P1)."""

    def _args(self, tmp_path: Path, clobber: bool = False) -> argparse.Namespace:
        return argparse.Namespace(output_dir=tmp_path, clobber=clobber)

    def test_rejects_path_traversal_workflow_id(self, tmp_path: Path) -> None:
        """workflow_id containing path separators raises ValueError."""
        provider = MagicMock()
        provider.answers = {"workflow_id": "../etc"}
        with pytest.raises(ValueError, match="path separator"):
            _write_init_artifacts(provider, self._args(tmp_path))

    def test_rejects_nested_workflow_id(self, tmp_path: Path) -> None:
        """workflow_id with nested path components raises ValueError."""
        provider = MagicMock()
        provider.answers = {"workflow_id": "foo/bar"}
        with pytest.raises(ValueError, match="path separator"):
            _write_init_artifacts(provider, self._args(tmp_path))

    def test_rejects_absolute_workflow_id(self, tmp_path: Path) -> None:
        """Absolute workflow_id raises ValueError, preventing output_dir bypass."""
        provider = MagicMock()
        provider.answers = {"workflow_id": "/tmp/attack"}
        with pytest.raises(ValueError, match="path separator"):
            _write_init_artifacts(provider, self._args(tmp_path))

    def test_accepts_simple_workflow_id(self, tmp_path: Path) -> None:
        """A plain name with no separators is accepted."""
        provider = MagicMock()
        provider.answers = {"workflow_id": "my_workflow"}
        provider.dump = MagicMock()
        _write_init_artifacts(provider, self._args(tmp_path))
        provider.dump.assert_called_once_with(tmp_path / "my_workflow")
