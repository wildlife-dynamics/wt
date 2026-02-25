"""Tests for wizard extensibility — overrides, conditional branching, custom providers."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from wt_compiler.wizard.abstract import (
    AbstractWizardProvider,
    SingleWizardQuestion,
    WizardQuestion,
    WizardQuestionLoop,
    with_condition,
)
from wt_compiler.wizard.default import DefaultWizardProvider, non_empty_str


def drive_wizard(
    provider: AbstractWizardProvider, answers: list[str | None]
) -> list[dict]:
    """Drive wizard generator with a sequence of answers. Returns all yielded questions."""
    gen = provider.input_generator()
    questions: list[dict] = []
    try:
        q = next(gen)
        questions.append(q)
        for ans in answers:
            q = gen.send(ans)
            questions.append(q)
    except StopIteration:
        pass
    return questions


class TestCustomProviderConformance:
    """Tests for custom provider subclassing."""

    def test_custom_provider_is_subclass(self) -> None:
        """A subclass that overrides abstract methods is a valid AbstractWizardProvider subclass."""

        class CustomProvider(AbstractWizardProvider):
            def get_questions(self) -> list[WizardQuestion]:
                return [
                    SingleWizardQuestion(
                        {
                            "dest": "custom_field",
                            "argparse": {"help": "Custom field", "type": str},
                            "wizard": {},
                        }
                    )
                ]

        assert issubclass(CustomProvider, AbstractWizardProvider)
        p = CustomProvider()
        gen = p.input_generator()
        q = next(gen)
        assert q["dest"] == "custom_field"


class TestOverrideGetQuestions:
    """Tests for overriding get_questions() in subclasses."""

    def test_override_get_questions_add_question(self) -> None:
        """Subclass adds a custom question, verify it is collected."""

        class ExtendedProvider(DefaultWizardProvider):
            def get_questions(self) -> list[WizardQuestion]:
                qs = super().get_questions()
                qs.insert(
                    1,
                    SingleWizardQuestion(
                        {
                            "dest": "custom_field",
                            "argparse": {"help": "Custom field", "type": str},
                            "wizard": {},
                        }
                    ),
                )
                return qs

        provider = ExtendedProvider()
        answers = [
            "my_workflow",  # workflow_id
            "custom_value",  # custom_field (inserted at position 1)
            "My Workflow",  # workflow_name
            "desc",  # workflow_description
            "Author",  # author_name
            "MIT",  # license_type
            "",  # end requirements loop
        ]
        drive_wizard(provider, answers)
        assert provider.answers["custom_field"] == "custom_value"

    def test_override_get_questions_remove_question(self) -> None:
        """Subclass removes license_type, verify it's never yielded."""

        class NoLicenseProvider(DefaultWizardProvider):
            def get_questions(self) -> list[WizardQuestion]:
                return [q for q in super().get_questions() if q["dest"] != "license_type"]

        provider = NoLicenseProvider()
        answers = [
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "",  # end requirements
        ]
        questions = drive_wizard(provider, answers)
        dests = [q["dest"] for q in questions]
        assert "license_type" not in dests

    def test_override_get_questions_modify_question(self) -> None:
        """Subclass modifies license choices, verify modified choices yielded."""

        class ModifiedLicenseProvider(DefaultWizardProvider):
            def get_questions(self) -> list[WizardQuestion]:
                qs = super().get_questions()
                for q in qs:
                    if q["dest"] == "license_type":
                        q["argparse"]["choices"] = ["MIT", "Unlicense"]
                return qs

        provider = ModifiedLicenseProvider()
        gen = provider.input_generator()
        q = next(gen)
        # Drive to license question
        q = gen.send("my_workflow")
        q = gen.send("Name")
        q = gen.send("desc")
        q = gen.send("Author")
        assert q["dest"] == "license_type"
        assert q["argparse"]["choices"] == ["MIT", "Unlicense"]

    def test_override_get_questions_reorder(self) -> None:
        """Subclass reorders questions, verify they yield in new order."""

        class ReorderedProvider(DefaultWizardProvider):
            def get_questions(self) -> list[WizardQuestion]:
                qs = super().get_questions()
                # Move workflow_name to first position
                name_q = next(q for q in qs if q["dest"] == "workflow_name")
                qs.remove(name_q)
                qs.insert(0, name_q)
                return qs

        provider = ReorderedProvider()
        gen = provider.input_generator()
        q = next(gen)
        assert q["dest"] == "workflow_name"


class TestCustomTypeCallable:
    """Tests for custom type callable validation."""

    def test_custom_type_callable_validation(self) -> None:
        """Subclass with custom type callable that raises, verify re-yield with error."""

        def positive_int(value: str) -> int:
            v = int(value)
            if v <= 0:
                raise argparse.ArgumentTypeError("Must be positive")
            return v

        class CustomTypeProvider(AbstractWizardProvider):
            def get_questions(self) -> list[WizardQuestion]:
                return [
                    SingleWizardQuestion(
                        {
                            "dest": "count",
                            "argparse": {"help": "Count", "type": positive_int},
                            "wizard": {},
                        }
                    )
                ]

        provider = CustomTypeProvider()
        gen = provider.input_generator()
        q = next(gen)
        assert q["dest"] == "count"
        # Send invalid value
        q = gen.send("-5")
        assert "error" in q["wizard"]
        assert "positive" in q["wizard"]["error"].lower()


class TestConditionalQuestions:
    """Tests for condition-gated questions."""

    def _make_conditional_provider(self) -> type[AbstractWizardProvider]:
        """Create a provider with a conditional question."""

        class ConditionalProvider(AbstractWizardProvider):
            def get_questions(self) -> list[WizardQuestion]:
                return [
                    SingleWizardQuestion(
                        {
                            "dest": "workflow_id",
                            "argparse": {"help": "Workflow ID", "type": str},
                            "wizard": {},
                        }
                    ),
                    SingleWizardQuestion(
                        {
                            "dest": "test_detail",
                            "argparse": {"help": "Test detail", "type": str},
                            "wizard": {
                                "condition": lambda a: a.get("workflow_id", "").startswith(
                                    "test_"
                                )
                            },
                        }
                    ),
                ]

        return ConditionalProvider

    def test_conditional_question_asked_when_condition_true(self) -> None:
        """Conditional question is yielded when condition returns True."""
        ProviderClass = self._make_conditional_provider()
        provider = ProviderClass()
        questions = drive_wizard(provider, ["test_foo", "detail_value"])
        dests = [q["dest"] for q in questions]
        assert "test_detail" in dests

    def test_conditional_question_skipped_when_condition_false(self) -> None:
        """Conditional question is NOT yielded when condition returns False."""
        ProviderClass = self._make_conditional_provider()
        provider = ProviderClass()
        questions = drive_wizard(provider, ["my_wf"])
        dests = [q["dest"] for q in questions]
        assert "test_detail" not in dests

    def test_mutually_exclusive_branches(self) -> None:
        """Two branches with mutually exclusive conditions — only correct branch asked."""

        class BranchProvider(AbstractWizardProvider):
            def get_questions(self) -> list[WizardQuestion]:
                return [
                    SingleWizardQuestion(
                        {
                            "dest": "variant",
                            "argparse": {
                                "help": "Variant",
                                "type": str,
                                "choices": ["gcp", "local"],
                            },
                            "wizard": {},
                        }
                    ),
                    SingleWizardQuestion(
                        {
                            "dest": "gcp_project",
                            "argparse": {"help": "GCP project", "type": str},
                            "wizard": {
                                "condition": lambda a: a.get("variant") == "gcp"
                            },
                        }
                    ),
                    SingleWizardQuestion(
                        {
                            "dest": "local_path",
                            "argparse": {"help": "Local path", "type": str},
                            "wizard": {
                                "condition": lambda a: a.get("variant") == "local"
                            },
                        }
                    ),
                ]

        # GCP branch
        provider_gcp = BranchProvider()
        questions_gcp = drive_wizard(provider_gcp, ["gcp", "my-project"])
        dests_gcp = [q["dest"] for q in questions_gcp]
        assert "gcp_project" in dests_gcp
        assert "local_path" not in dests_gcp

        # Local branch
        provider_local = BranchProvider()
        questions_local = drive_wizard(provider_local, ["local", "/tmp/out"])
        dests_local = [q["dest"] for q in questions_local]
        assert "local_path" in dests_local
        assert "gcp_project" not in dests_local

    def test_condition_inspects_answers_proxy(self) -> None:
        """Condition callable receives MappingProxyType, not mutable _answers dict."""
        received_type = None

        def capture_type(answers: Any) -> bool:
            nonlocal received_type
            received_type = type(answers)
            return True

        class InspectorProvider(AbstractWizardProvider):
            def get_questions(self) -> list[WizardQuestion]:
                return [
                    SingleWizardQuestion(
                        {
                            "dest": "first",
                            "argparse": {"help": "First", "type": str},
                            "wizard": {},
                        }
                    ),
                    SingleWizardQuestion(
                        {
                            "dest": "second",
                            "argparse": {"help": "Second", "type": str},
                            "wizard": {"condition": capture_type},
                        }
                    ),
                ]

        provider = InspectorProvider()
        drive_wizard(provider, ["value1", "value2"])
        assert received_type is MappingProxyType


class TestWithCondition:
    """Tests for with_condition() helper."""

    def test_with_condition_composes_branches(self) -> None:
        """with_condition() applies condition to both SingleWizardQuestion and WizardQuestionLoop."""
        cond = lambda a: a.get("mode") == "advanced"

        single_q = SingleWizardQuestion(
            {"dest": "detail", "argparse": {"help": "Detail", "type": str}, "wizard": {}}
        )
        loop_q = WizardQuestionLoop(
            {
                "dest": "items",
                "questions": [
                    SingleWizardQuestion(
                        {
                            "dest": "item_name",
                            "argparse": {"help": "Item name", "type": non_empty_str},
                            "wizard": {},
                        }
                    )
                ],
            }
        )

        gated = with_condition([single_q, loop_q], cond)

        # SingleWizardQuestion: condition set on wizard
        assert gated[0]["wizard"]["condition"] is cond
        # WizardQuestionLoop: condition set at top level
        assert gated[1]["condition"] is cond

    def test_with_condition_drives_correctly(self) -> None:
        """Drive a wizard with with_condition() applied branches."""

        class BranchProvider(AbstractWizardProvider):
            def get_questions(self) -> list[WizardQuestion]:
                base = [
                    SingleWizardQuestion(
                        {
                            "dest": "mode",
                            "argparse": {
                                "help": "Mode",
                                "type": str,
                                "choices": ["simple", "advanced"],
                            },
                            "wizard": {},
                        }
                    ),
                ]
                advanced_qs: list[WizardQuestion] = [
                    SingleWizardQuestion(
                        {
                            "dest": "extra",
                            "argparse": {"help": "Extra", "type": str},
                            "wizard": {},
                        }
                    )
                ]
                return base + with_condition(
                    advanced_qs, lambda a: a.get("mode") == "advanced"
                )

        # Advanced mode — extra question asked
        p1 = BranchProvider()
        qs1 = drive_wizard(p1, ["advanced", "extra_val"])
        assert "extra" in [q["dest"] for q in qs1]
        assert p1.answers["extra"] == "extra_val"

        # Simple mode — extra question skipped
        p2 = BranchProvider()
        qs2 = drive_wizard(p2, ["simple"])
        assert "extra" not in [q["dest"] for q in qs2]


class TestCustomTemplates:
    """Tests for MRO-based template resolution."""

    def test_custom_template_overrides_default(self, tmp_path: Path) -> None:
        """Subclass provides templates/spec.yaml.jinja2 overriding the default."""
        # Create a temporary module with custom template
        custom_templates = tmp_path / "custom_templates"
        custom_templates.mkdir()
        (custom_templates / "spec.yaml.jinja2").write_text(
            "# Custom spec\nid: {{ workflow_id }}\n"
        )

        provider = DefaultWizardProvider()
        answers = [
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "MIT",
            "",  # end requirements
        ]
        drive_wizard(provider, answers)

        # Manually test MRO override by manipulating the loader
        import jinja2

        custom_loader = jinja2.FileSystemLoader(str(custom_templates))
        default_template_dir = (
            Path(__file__).parent.parent
            / "src"
            / "wt_compiler"
            / "wizard"
            / "templates"
        )
        default_loader = jinja2.FileSystemLoader(str(default_template_dir))
        env = jinja2.Environment(
            loader=jinja2.ChoiceLoader([custom_loader, default_loader]),
            keep_trailing_newline=True,
            undefined=jinja2.StrictUndefined,
        )
        template = env.get_template("spec.yaml.jinja2")
        result = template.render(**provider._answers, year=2024)
        assert result.startswith("# Custom spec")

    def test_custom_template_adds_new_artifact(self, tmp_path: Path) -> None:
        """Subclass provides templates/extra.yaml.jinja2 for a new artifact."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "MIT",
            "",
        ]
        drive_wizard(provider, answers)
        provider.dump(tmp_path)

        # Default files exist
        assert (tmp_path / "spec.yaml").exists()
        assert (tmp_path / "README.md").exists()
        # 6 total files
        files = [f.name for f in tmp_path.iterdir() if f.is_file()]
        assert len(files) == 6

    def test_default_templates_inherited(self, tmp_path: Path) -> None:
        """Subclass with no custom templates inherits all defaults."""
        provider = DefaultWizardProvider()
        answers = [
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "MIT",
            "",
        ]
        drive_wizard(provider, answers)
        provider.dump(tmp_path)

        expected = {"spec.yaml", "test-cases.yaml", "README.md", "LICENSE", ".gitignore", ".gitattributes"}
        actual = {f.name for f in tmp_path.iterdir() if f.is_file()}
        assert expected == actual
