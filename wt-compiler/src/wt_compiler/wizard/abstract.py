"""Abstract wizard provider and question type definitions.

Defines the ``AbstractWizardProvider`` ABC and the ``WizardQuestion`` family of
TypedDicts used by wizard providers to describe interactive project-scaffolding
questions.  A future CLI consumes the generator protocol to drive both
interactive (``input()``) and batch (``argparse``) modes.

Examples:
    Subclass ``AbstractWizardProvider`` and implement ``get_questions()``::

        >>> from wt_compiler.wizard.abstract import (
        ...     AbstractWizardProvider,
        ...     WizardQuestion,
        ... )
        >>> class MyProvider(AbstractWizardProvider):
        ...     def get_questions(self):
        ...         return [{"dest": "name", "argparse": {"help": "Name"}, "wizard": {}}]
"""

from __future__ import annotations

import argparse
import datetime
import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypedDict, TypeGuard, cast

import jinja2


class ArgparseKwargs(TypedDict, total=False):
    """Kwargs passable directly to ``argparse.ArgumentParser.add_argument()``.

    All fields are optional since different question types use different
    subsets of argparse kwargs.
    """

    type: Callable[[str], Any]
    choices: list[str]
    nargs: str
    default: Any
    action: str
    metavar: str
    help: str


class WizardKwargs(TypedDict, total=False):
    """Wizard-specific metadata not passed to argparse.

    All fields are optional — ``error`` is only present on re-yield after
    validation failure, and ``condition`` is only present on gated questions.
    """

    error: str
    condition: Callable[[MappingProxyType[str, Any]], bool]


class SingleWizardQuestion(TypedDict):
    """A single question yielded by the wizard."""

    dest: str
    argparse: ArgparseKwargs
    wizard: WizardKwargs


class WizardQuestionLoop(TypedDict, total=False):
    """A repeating group of questions that collects a list of dicts.

    The ``questions`` list is asked as a group, repeated until the user
    signals "done" by sending an empty/None answer to the first question.

    Constraint: the first question's ``type`` callable MUST reject
    empty/None input (e.g., ``non_empty_str``), so empty/None
    unambiguously signals loop termination.

    Recursive nesting is supported: a question in ``questions`` can
    itself be a ``WizardQuestionLoop``.
    """

    dest: str  # pyright: ignore[reportGeneralTypeIssues]  # Required
    questions: list[WizardQuestion]  # pyright: ignore[reportGeneralTypeIssues]  # Required
    condition: Callable[[MappingProxyType[str, Any]], bool]


WizardQuestion = SingleWizardQuestion | WizardQuestionLoop
"""Union type for questions yielded by a wizard provider."""


def _is_loop(q: WizardQuestion) -> TypeGuard[WizardQuestionLoop]:
    """Runtime type guard: ``True`` if *q* is a ``WizardQuestionLoop``."""
    return "questions" in q


def with_condition(
    questions: list[WizardQuestion],
    condition: Callable[[MappingProxyType[str, Any]], bool],
) -> list[WizardQuestion]:
    """Apply a condition gate to all questions in a branch.

    Enables composing question branches separately and splicing
    them together with a conditional gate.

    Handles both ``SingleWizardQuestion`` (sets ``wizard.condition``)
    and ``WizardQuestionLoop`` (sets top-level ``condition``).

    Args:
        questions: List of questions to gate.
        condition: Callable receiving read-only answers proxy, returns bool.

    Returns:
        New list of questions with the condition applied.

    Examples:
        >>> qs = [{"dest": "x", "argparse": {"help": "X"}, "wizard": {}}]
        >>> gated = with_condition(qs, lambda a: a.get("mode") == "advanced")
        >>> gated[0]["wizard"]["condition"]  # doctest: +ELLIPSIS
        <function ...>
    """
    result: list[WizardQuestion] = []
    for q in questions:
        if _is_loop(q):
            result.append(cast(WizardQuestion, {**q, "condition": condition}))
        else:
            wiz = cast(SingleWizardQuestion, q)
            result.append(
                cast(
                    WizardQuestion,
                    {**wiz, "wizard": {**wiz.get("wizard", {}), "condition": condition}},
                )
            )
    return result


def _make_loop_type(
    questions: list[WizardQuestion],
) -> Callable[[str], dict[str, Any]]:
    """Build a composite argparse type callable from loop sub-questions.

    Parses JSON, then validates each sub-field using its question's
    ``type``/``choices``.

    Args:
        questions: Sub-questions defining the loop body fields.

    Returns:
        A callable suitable for ``argparse.add_argument(type=...)``.
    """

    def type_fn(value: str) -> dict[str, Any]:
        try:
            d = json.loads(value)
        except json.JSONDecodeError as e:
            raise argparse.ArgumentTypeError(f"Invalid JSON: {e}") from e
        if not isinstance(d, dict):
            raise argparse.ArgumentTypeError(f"Expected a JSON object (got {type(d).__name__})")
        for _sub_q in questions:
            sq = cast(SingleWizardQuestion, _sub_q)
            dest = sq["dest"]
            if dest not in d:
                default = sq.get("argparse", {}).get("default")
                if default is not None:
                    d[dest] = default
                    continue
                raise argparse.ArgumentTypeError(f"Missing required field: {dest}")
            sub_type_fn = sq.get("argparse", {}).get("type", str)
            try:
                d[dest] = sub_type_fn(d[dest])
            except (ValueError, argparse.ArgumentTypeError) as e:
                raise argparse.ArgumentTypeError(f"Invalid {dest}: {e}") from e
            choices = sq.get("argparse", {}).get("choices")
            if choices and d[dest] not in choices:
                raise argparse.ArgumentTypeError(f"Invalid {dest}: must be one of {choices}")
        return d

    return type_fn


class AbstractWizardProvider(ABC):
    """Abstract base class for wizard providers.

    Provides a concrete generic ``input_generator()`` that subclasses inherit.
    Subclasses must implement ``get_questions()`` to define the question flow.

    The generator protocol:

    1. Caller: ``question = next(gen)`` — gets first question.
    2. Caller: ``question = gen.send(answer_str)`` — sends answer, gets next
       question (or re-yield with ``error`` on validation failure).
    3. Generator stores valid answers on ``self._answers``.
    4. Generator raises ``StopIteration`` when all questions are answered.

    Examples:
        >>> class MinimalProvider(AbstractWizardProvider):
        ...     def get_questions(self):
        ...         return [{"dest": "name", "argparse": {"help": "Name"}, "wizard": {}}]
        >>> p = MinimalProvider()
        >>> gen = p.input_generator()
        >>> q = next(gen)
        >>> q["dest"]
        'name'
    """

    def __init__(self) -> None:
        self._answers: dict[str, Any] = {}

    @property
    def answers(self) -> MappingProxyType[str, Any]:
        """Read-only view of collected answers."""
        return MappingProxyType(self._answers)

    @abstractmethod
    def get_questions(self) -> list[WizardQuestion]:
        """Return the ordered list of questions for this wizard.

        Override in subclasses to define the question flow.
        """
        ...

    def _validate_answer(
        self, question: SingleWizardQuestion, answer: str | None
    ) -> Generator[SingleWizardQuestion, str | None, Any]:
        """Validate/coerce answer via the question's type callable.

        Re-yields question with error on validation failure until a valid
        answer is received.

        Args:
            question: The question being answered.
            answer: The raw answer string.

        Returns:
            The coerced/validated answer value.
        """
        type_fn = question.get("argparse", {}).get("type", str)
        while True:
            try:
                return type_fn(answer) if answer is not None else answer
            except (ValueError, argparse.ArgumentTypeError) as e:
                answer = yield {
                    **question,
                    "wizard": {**question.get("wizard", {}), "error": str(e)},
                }

    def _process_question(
        self, question: WizardQuestion
    ) -> Generator[SingleWizardQuestion, str | None, Any]:
        """Process a single question or loop group, recursively via yield from.

        Args:
            question: A ``SingleWizardQuestion`` or ``WizardQuestionLoop``.

        Returns:
            The validated answer (single value or list of dicts for loops).
        """
        if _is_loop(question):
            # WizardQuestionLoop
            results: list[dict[str, Any]] = []
            first_q = cast(SingleWizardQuestion, question["questions"][0])
            answer = yield first_q
            while answer:  # empty/None on first question = done
                coerced = yield from self._validate_answer(first_q, answer)
                entry = {first_q["dest"]: coerced}
                for sub_q in question["questions"][1:]:
                    sub_value = yield from self._process_question(sub_q)  # recursive
                    entry[sub_q["dest"]] = sub_value
                results.append(entry)
                answer = yield first_q  # re-yield first question for next iteration
            return results
        else:
            # SingleWizardQuestion
            single = cast(SingleWizardQuestion, question)
            answer = yield single
            coerced = yield from self._validate_answer(single, answer)
            default = single.get("argparse", {}).get("default")
            if coerced is None or coerced == "":
                return default
            return coerced

    def input_generator(
        self,
    ) -> Generator[SingleWizardQuestion, str | None, None]:
        """Generic generator loop driving the wizard question flow.

        Iterates ``get_questions()``, validates via type callables,
        handles re-yields on error and loop questions.  Uses
        ``_process_question()`` with ``yield from`` for recursive
        ``WizardQuestionLoop`` support.

        Concrete — rarely needs overriding.

        Yields:
            ``SingleWizardQuestion`` dicts (never ``WizardQuestionLoop``).
        """
        for question in self.get_questions():
            # Condition check — works for both SingleWizardQuestion and
            # WizardQuestionLoop
            if _is_loop(question):
                condition = question.get("condition")
            else:
                condition = cast(SingleWizardQuestion, question).get("wizard", {}).get("condition")
            if condition and not condition(self.answers):
                continue
            result = yield from self._process_question(question)
            # Enforce argparse.choices for single questions in interactive mode
            if not _is_loop(question):
                argparse_kwargs = cast(SingleWizardQuestion, question).get("argparse", {})
                choices = argparse_kwargs.get("choices")
                if choices is not None and result not in choices:
                    raise ValueError(
                        f"Invalid choice {result!r} for {question['dest']!r}; "
                        f"expected one of {choices!r}"
                    )
            self._answers[question["dest"]] = result

    def dump(self, workdir: Path) -> None:
        """Render templates to *workdir* using collected answers.

        Convention-based template rendering with MRO-based fallback:

        1. Walks the class MRO to find ``templates/`` dirs colocated with
           each class's module.
        2. Creates a Jinja ``ChoiceLoader`` (subclass-first priority).
        3. Collects the union of all top-level ``*.jinja2`` filenames.
        4. Renders each template with ``{**self._answers, year=<current_year>}``.
        5. Output filename = template filename minus ``.jinja2`` suffix.

        Subclasses can override a default template by providing one with the
        same name, add new templates for additional artifacts, or inherit all
        other default templates without copying them.

        Args:
            workdir: Directory to write rendered files into.

        Raises:
            jinja2.UndefinedError: If answers are missing for a template.
        """
        # Build loaders from MRO (subclass-first)
        loaders: list[jinja2.PackageLoader] = []
        seen_modules: set[str] = set()
        for cls in type(self).__mro__:
            if cls is object:
                continue
            mod = cls.__module__
            if mod in seen_modules:
                continue
            seen_modules.add(mod)
            try:
                loaders.append(jinja2.PackageLoader(mod, "templates"))
            except ValueError:
                continue

        if not loaders:
            raise RuntimeError(
                f"{type(self).__qualname__}.dump() found no template loaders. "
                "Ensure the 'templates/' directory is included in the package data."
            )

        env = jinja2.Environment(
            loader=jinja2.ChoiceLoader(loaders),
            keep_trailing_newline=True,
            undefined=jinja2.StrictUndefined,
        )

        # Collect union of all *.jinja2 template names
        template_names: set[str] = set()
        for loader in loaders:
            template_names.update(
                name for name in loader.list_templates() if name.endswith(".jinja2")
            )

        if not template_names:
            raise RuntimeError(
                f"{type(self).__qualname__}.dump() found no *.jinja2 templates. "
                "Ensure the 'templates/' directory is included in the package data."
            )

        # Render each template
        context = {**self._answers, "year": datetime.datetime.now().year}
        workdir.mkdir(parents=True, exist_ok=True)
        for tname in sorted(template_names):
            template = env.get_template(tname)
            output_name = tname.removesuffix(".jinja2")
            output_path = workdir / output_name
            output_path.write_text(template.render(context))
