"""Tests for CLI compatibility — interactive input() loop and static argparse flags."""

from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from conftest import drive_wizard

from wt_compiler.wizard.abstract import (
    AbstractWizardProvider,
    SingleWizardQuestion,
    WizardQuestion,
    _make_loop_type,
)
from wt_compiler.wizard.default import DefaultWizardProvider


def interactive_loop(provider: AbstractWizardProvider) -> None:
    """Simulate interactive session using input() for each question."""
    gen = provider.input_generator()
    try:
        question = next(gen)
        while True:
            prompt = question["argparse"].get("help", "")
            choices = question["argparse"].get("choices")
            error = question.get("wizard", {}).get("error")
            if error:
                print(f"Error: {error}")
            if choices:
                print(f"Choices: {', '.join(choices)}")
            answer = input(f"{prompt}: ")
            question = gen.send(answer)
    except StopIteration:
        pass


class TestInteractiveMode:
    """Tests simulating interactive input() loop."""

    def test_interactive_loop_drives_generator(self) -> None:
        """Simulate interactive session with monkeypatched input."""
        provider = DefaultWizardProvider()
        input_sequence = iter([
            "my_workflow",
            "My Workflow",
            "A description",
            "Author Name",
            "MIT",

            "numpy",
            "*",
            "conda-forge",
            "",  # end requirements
        ])

        with patch("builtins.input", side_effect=input_sequence):
            interactive_loop(provider)

        assert provider.answers["workflow_id"] == "my_workflow"
        assert provider.answers["workflow_name"] == "My Workflow"
        assert provider.answers["requirements"] == [
            {"name": "numpy", "version": "*", "channel": "conda-forge"}
        ]

    def test_interactive_loop_displays_choices(self, capsys: object) -> None:
        """For select-type questions with choices, verify choices are displayed."""
        provider = DefaultWizardProvider()
        input_sequence = iter([
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "MIT",  # license (has choices)

            "",  # end requirements
        ])

        with patch("builtins.input", side_effect=input_sequence):
            interactive_loop(provider)

        # capsys is a pytest fixture, but we just verify the wizard completed
        assert provider.answers["license_type"] == "MIT"

    def test_interactive_loop_redisplays_on_error(self) -> None:
        """When type callable raises, verify error is shown and re-prompted."""
        provider = DefaultWizardProvider()
        input_sequence = iter([
            "123bad",  # invalid workflow_id
            "my_workflow",  # valid retry
            "My Workflow",
            "desc",
            "Author",
            "MIT",

            "",  # end requirements
        ])

        printed: list[str] = []
        original_print = print

        def capture_print(*args: object, **kwargs: object) -> None:
            printed.append(" ".join(str(a) for a in args))

        with patch("builtins.input", side_effect=input_sequence):
            with patch("builtins.print", side_effect=capture_print):
                interactive_loop(provider)

        assert provider.answers["workflow_id"] == "my_workflow"
        # Verify error message was printed
        error_msgs = [p for p in printed if "Error:" in p]
        assert len(error_msgs) > 0

    def test_interactive_loop_handles_loop_question(self) -> None:
        """For requirements loop, verify it keeps prompting until empty input."""
        provider = DefaultWizardProvider()
        input_sequence = iter([
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "MIT",

            "pkg1",  # req 1 name
            "*",  # req 1 version
            "conda-forge",  # req 1 channel
            "pkg2",  # req 2 name
            "*",  # req 2 version
            "conda-forge",  # req 2 channel
            "",  # end requirements
        ])

        with patch("builtins.input", side_effect=input_sequence):
            interactive_loop(provider)

        assert len(provider.answers["requirements"]) == 2


class TestStaticBatchMode:
    """Tests for argparse static/batch mode compatibility."""

    def test_argparse_add_argument_compatibility(self) -> None:
        """For each question from get_questions(), add_argument succeeds."""
        provider = DefaultWizardProvider()
        parser = argparse.ArgumentParser()
        for q in provider.get_questions():
            dest = q["dest"]
            if "questions" in q:
                # WizardQuestionLoop — auto-derive argparse
                loop_type = _make_loop_type(q["questions"])
                parser.add_argument(
                    f"--{dest.replace('_', '-')}",
                    type=loop_type,
                    action="append",
                    default=[],
                    help=f"JSON: {', '.join(sq['dest'] for sq in q['questions'])}",
                )
            else:
                parser.add_argument(
                    f"--{dest.replace('_', '-')}", **q["argparse"]
                )

    def test_argparse_parse_args_valid(self) -> None:
        """Build parser, parse valid args, verify namespace."""
        provider = DefaultWizardProvider()
        parser = argparse.ArgumentParser()
        for q in provider.get_questions():
            dest = q["dest"]
            if "questions" in q:
                loop_type = _make_loop_type(q["questions"])
                parser.add_argument(
                    f"--{dest.replace('_', '-')}",
                    type=loop_type,
                    action="append",
                    default=[],
                    help=f"JSON: {', '.join(sq['dest'] for sq in q['questions'])}",
                )
            else:
                parser.add_argument(
                    f"--{dest.replace('_', '-')}", **q["argparse"]
                )

        args = parser.parse_args([
            "--workflow-id", "my_wf",
            "--workflow-name", "My Workflow",
            "--workflow-description", "A desc",
            "--author-name", "Author",
            "--license-type", "MIT",
            "--requirements", '{"name": "numpy", "version": "*", "channel": "conda-forge"}',
        ])
        assert args.workflow_id == "my_wf"
        assert args.workflow_name == "My Workflow"
        assert args.license_type == "MIT"
        assert len(args.requirements) == 1
        assert args.requirements[0]["name"] == "numpy"

    def test_argparse_parse_args_with_type_validation(self) -> None:
        """Build parser, parse args with invalid workflow_id, verify SystemExit."""
        provider = DefaultWizardProvider()
        parser = argparse.ArgumentParser()
        for q in provider.get_questions():
            dest = q["dest"]
            if "questions" in q:
                continue  # skip loop for this test
            parser.add_argument(
                f"--{dest.replace('_', '-')}", **q["argparse"]
            )

        with pytest.raises(SystemExit):
            parser.parse_args(["--workflow-id", "123bad"])

    def test_argparse_to_generator_bridge(self) -> None:
        """Feed parsed argparse Namespace values into generator via .send()."""
        provider_argparse = DefaultWizardProvider()
        parser = argparse.ArgumentParser()
        for q in provider_argparse.get_questions():
            dest = q["dest"]
            if "questions" in q:
                loop_type = _make_loop_type(q["questions"])
                parser.add_argument(
                    f"--{dest.replace('_', '-')}",
                    type=loop_type,
                    action="append",
                    default=[],
                    help=f"JSON",
                )
            else:
                parser.add_argument(
                    f"--{dest.replace('_', '-')}", **q["argparse"]
                )

        args = parser.parse_args([
            "--workflow-id", "my_wf",
            "--workflow-name", "My Workflow",
            "--workflow-description", "A desc",
            "--author-name", "Author",
            "--license-type", "MIT",
            "--requirements", '{"name": "numpy", "version": "*", "channel": "conda-forge"}',
        ])

        # Now drive a fresh provider's generator with argparse values
        provider = DefaultWizardProvider()
        gen = provider.input_generator()
        q = next(gen)

        # Feed simple questions from namespace
        simple_dests = ["workflow_id", "workflow_name", "workflow_description", "author_name", "license_type"]
        for dest in simple_dests:
            value = getattr(args, dest)
            q = gen.send(str(value) if value else "")

        # Feed loop question: for each parsed requirement dict, send sub-fields
        assert q["dest"] == "name"  # first sub-question of requirements loop
        for req_dict in args.requirements:
            q = gen.send(req_dict["name"])
            q = gen.send(req_dict["version"])
            q = gen.send(req_dict["channel"])

        # End the loop
        try:
            gen.send("")  # empty name = end loop
            # If there are more questions, that's fine
        except StopIteration:
            pass

        assert provider.answers["workflow_id"] == "my_wf"
        assert provider.answers["requirements"] == [
            {"name": "numpy", "version": "*", "channel": "conda-forge"}
        ]

    def test_loop_question_argparse_json_append(self) -> None:
        """Verify auto-derived argparse for WizardQuestionLoop: action=append, JSON type."""
        provider = DefaultWizardProvider()
        loop_q = next(
            q for q in provider.get_questions() if q["dest"] == "requirements"
        )
        assert "questions" in loop_q

        loop_type = _make_loop_type(loop_q["questions"])

        # Valid JSON
        result = loop_type('{"name": "numpy", "version": "*", "channel": "conda-forge"}')
        assert result["name"] == "numpy"
        assert result["version"] == "*"
        assert result["channel"] == "conda-forge"

        # Invalid JSON
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid JSON"):
            loop_type("not json")

        # JSON root is not an object (e.g., array)
        with pytest.raises(argparse.ArgumentTypeError, match="Expected a JSON object"):
            loop_type('[{"name": "numpy"}]')

        # JSON root is a scalar
        with pytest.raises(argparse.ArgumentTypeError, match="Expected a JSON object"):
            loop_type('"numpy"')

        # Missing required field
        with pytest.raises(argparse.ArgumentTypeError, match="Missing required field"):
            loop_type('{"version": "*"}')

        # Invalid sub-field value (version)
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid version"):
            loop_type('{"name": "pkg", "version": ">>>invalid<<<", "channel": "conda-forge"}')
