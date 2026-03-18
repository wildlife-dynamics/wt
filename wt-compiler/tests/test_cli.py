"""Tests for CLI functionality."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wt_compiler.cli import main


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

    def test_init_interactive_mode(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Interactive mode: input() drives wizard, dump() called with correct workdir."""
        input_sequence = iter([
            "my_workflow",    # workflow_id
            "My Workflow",    # workflow_name
            "A description",  # workflow_description
            "Author",         # author_name
            "MIT",            # license_type (valid choice — no pre-validation error)
            "",               # end requirements loop
        ])

        with patch.object(sys, "argv", ["wt-compiler", "init", "--output-dir", str(tmp_path)]):
            with patch("builtins.input", side_effect=input_sequence):
                with patch(
                    "wt_compiler.wizard.abstract.AbstractWizardProvider.dump"
                ) as mock_dump:
                    main()

        mock_dump.assert_called_once()
        assert mock_dump.call_args[0][0] == tmp_path / "my_workflow"

    def test_init_interactive_choices_prevalidation(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Interactive mode: invalid choice is re-prompted without calling gen.send()."""
        inputs = [
            "my_workflow",
            "My Workflow",
            "A description",
            "Author",
            "INVALID",  # invalid license_type — triggers pre-validation error, no gen.send()
            "MIT",      # valid retry
            "",         # end requirements loop
        ]

        with patch.object(sys, "argv", ["wt-compiler", "init", "--output-dir", str(tmp_path)]):
            with patch("builtins.input", side_effect=inputs) as mock_input:
                with patch(
                    "wt_compiler.wizard.abstract.AbstractWizardProvider.dump"
                ) as mock_dump:
                    main()

        mock_dump.assert_called_once()
        # 7 input() calls: 5 valid answers + 1 invalid (re-prompt, no gen.send) + 1 loop terminator
        assert mock_input.call_count == len(inputs)
        assert "not a valid choice" in capsys.readouterr().err

    def test_init_interactive_validation_reprompt(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Interactive mode: type validation failure (invalid workflow_id) re-prompts."""
        input_sequence = iter([
            "123bad",      # invalid workflow_id — _validate_answer re-yields with error
            "my_workflow", # valid retry
            "My Workflow",
            "A description",
            "Author",
            "MIT",
            "",            # end requirements loop
        ])

        with patch.object(sys, "argv", ["wt-compiler", "init", "--output-dir", str(tmp_path)]):
            with patch("builtins.input", side_effect=input_sequence):
                with patch(
                    "wt_compiler.wizard.abstract.AbstractWizardProvider.dump"
                ) as mock_dump:
                    main()

        mock_dump.assert_called_once()
        # Error message should contain the specific validation error from workflow_id_type
        assert "is not a valid Python identifier" in capsys.readouterr().err

    def test_init_existing_dir_error(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Error when workdir exists and --clobber not set."""
        (tmp_path / "my_workflow").mkdir()

        with patch.object(sys, "argv", [
            "wt-compiler", "init",
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

    def test_init_partial_batch_flags_error(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Providing some but not all required batch flags exits 1 with clear error."""
        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--workflow-id", "my_workflow",
            # missing --workflow-name and --author-name
            "--output-dir", str(tmp_path),
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "partial batch flags" in captured.err
        assert "--workflow-name" in captured.err
        assert "--author-name" in captured.err

    def test_init_optional_only_batch_flags_error(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Providing only optional batch flags without required flags exits 1."""
        with patch.object(sys, "argv", [
            "wt-compiler", "init",
            "--workflow-description", "A desc",
            "--output-dir", str(tmp_path),
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        assert "partial batch flags" in capsys.readouterr().err


class TestModuleEntryPoint:
    """Tests for python -m wt_compiler entry point."""

    def test_main_module_import(self) -> None:
        """Test that __main__.py can be imported."""
        import wt_compiler.__main__

        assert hasattr(wt_compiler.__main__, "main")
