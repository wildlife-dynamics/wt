# Plan: AbstractWizardProvider & DefaultWizardProvider

## Context

The `wt-compiler` package compiles `spec.yaml` files into executable workflow DAGs. Currently, users must hand-author their `spec.yaml` and surrounding project files from scratch. This change introduces a `AbstractWizardProvider` and a `DefaultWizardProvider` reference implementation to power a future `wt-compiler init` CLI subcommand that interactively scaffolds a new workflow project directory.

This phase implements only the ABC and default provider (not the CLI subcommand).

---

## New Files

```
wt-compiler/src/wt_compiler/wizard/
├── __init__.py          # Re-exports AbstractWizardProvider, DefaultWizardProvider, TypedDicts
├── abstract.py          # AbstractWizardProvider (ABC), WizardQuestion, ArgparseKwargs, WizardKwargs
├── default.py           # DefaultWizardProvider implementation
└── templates/           # Jinja2 templates for scaffold artifacts
    ├── spec.yaml.jinja2
    ├── test-cases.yaml.jinja2
    ├── README.md.jinja2
    ├── LICENSE.jinja2           # Uses {% include %} to select license variant
    ├── .gitignore.jinja2
    ├── .gitattributes.jinja2
    └── licenses/                # Partials (not rendered directly)
        ├── BSD-3-Clause.txt
        ├── MIT.txt
        └── Apache-2.0.txt

wt-compiler/tests/
├── test_wizard_abstract.py         # ABC conformance + generator mechanics
├── test_wizard_default.py         # DefaultWizardProvider questions, validation, dump
├── test_wizard_extensibility.py   # Extensibility: overrides, conditional branching, custom providers
└── test_wizard_cli_compat.py      # CLI compatibility: interactive input() loop + static argparse flags

wt-compiler/src/wt_compiler/wizard/
└── README.md                      # Implementor guide for custom wizard providers
```

---

## 1. `wizard/abstract.py` — AbstractWizardProvider & WizardQuestion

### WizardQuestion and nested TypedDicts

Self-describing types for yielded question dicts. Live in `abstract.py` alongside the ABC. The question dict nests argparse-compatible kwargs and wizard-specific kwargs under separate keys for clarity.

```python
from __future__ import annotations  # required for circular WizardQuestion reference

class ArgparseKwargs(TypedDict, total=False):
    """Kwargs passable directly to argparse.ArgumentParser.add_argument()."""
    type: type | Callable[[str], Any]  # Coercion callable (e.g., str, int)
    choices: list[str]                  # Restrict to these values
    nargs: str | int                    # e.g., "+" for one-or-more
    default: Any                        # Default if no answer given
    action: str                         # e.g., "store_true"
    metavar: str                        # Placeholder in help text
    help: str                           # Help text / prompt string

class WizardKwargs(TypedDict, total=False):
    """Wizard-specific metadata not passed to argparse."""
    error: str                          # Validation error (present on re-yield)
    condition: Callable[[MappingProxyType[str, Any]], bool]  # Gate: skip if returns False

class SingleWizardQuestion(TypedDict):
    """A single question yielded by the wizard."""
    dest: str                           # Answer key, usable as argparse dest
    argparse: ArgparseKwargs            # Kwargs for argparse.add_argument()
    wizard: WizardKwargs                # Wizard-specific metadata

class WizardQuestionLoop(TypedDict, total=False):
    """A repeating group of questions that collects a list of dicts.

    The ``questions`` list is asked as a group, repeated until the user
    signals "done" by sending an empty/None answer to the first question.

    Constraint: the first question's ``type`` callable MUST reject
    empty/None input (e.g., ``non_empty_str``), so empty/None
    unambiguously signals loop termination.

    Recursive nesting is supported: a question in ``questions`` can
    itself be a ``WizardQuestionLoop``.

    Argparse representation is auto-derived from ``questions`` —
    ``--{dest.replace('_', '-')}`` flag with ``action="append"`` and a composite JSON
    type validator built from sub-questions' ``type``/``choices``.
    No explicit ``argparse`` field is needed on ``WizardQuestionLoop``."""
    dest: str                           # Key for the collected list (e.g., "requirements") [required]
    questions: list[WizardQuestion]     # Body questions asked per iteration (recursive) [required]
    condition: Callable[[MappingProxyType[str, Any]], bool]  # Gate: skip entire loop if returns False

WizardQuestion = SingleWizardQuestion | WizardQuestionLoop

def with_condition(
    questions: list[WizardQuestion],
    condition: Callable[[MappingProxyType[str, Any]], bool],
) -> list[WizardQuestion]:
    """Apply a condition gate to all questions in a branch.
    Enables composing question branches separately and splicing
    them together with a conditional gate.

    Handles both ``SingleWizardQuestion`` (sets ``wizard.condition``)
    and ``WizardQuestionLoop`` (sets top-level ``condition``)."""
```

A future CLI extracts `question["argparse"]` from each `SingleWizardQuestion` and passes it directly as `**kwargs` to `parser.add_argument(f"--{question['dest'].replace('_', '-')}", **question["argparse"])`. Argparse automatically maps hyphenated flags (e.g., `--workflow-id`) back to underscore-based `dest` attributes. For `WizardQuestionLoop`, the argparse representation is auto-derived via `_make_loop_type()`:

```python
def _make_loop_type(questions: list[WizardQuestion]) -> Callable[[str], dict]:
    """Build a composite argparse type callable from loop sub-questions.
    Parses JSON, then validates each sub-field using its question's type/choices."""
    def type_fn(value: str) -> dict:
        try:
            d = json.loads(value)
        except json.JSONDecodeError as e:
            raise ArgumentTypeError(f"Invalid JSON: {e}")
        for sub_q in questions:
            dest = sub_q["dest"]
            if dest not in d:
                default = sub_q.get("argparse", {}).get("default")
                if default is not None:
                    d[dest] = default
                    continue
                raise ArgumentTypeError(f"Missing required field: {dest}")
            sub_type_fn = sub_q.get("argparse", {}).get("type", str)
            try:
                d[dest] = sub_type_fn(d[dest])
            except (ValueError, ArgumentTypeError) as e:
                raise ArgumentTypeError(f"Invalid {dest}: {e}")
            choices = sub_q.get("argparse", {}).get("choices")
            if choices and d[dest] not in choices:
                raise ArgumentTypeError(f"Invalid {dest}: must be one of {choices}")
        return d
    return type_fn
```

When building the argparse parser, detect `WizardQuestionLoop` and auto-generate:
```python
parser.add_argument(
    f'--{loop_q["dest"].replace("_", "-")}',
    type=_make_loop_type(loop_q["questions"]),
    action="append",
    default=[],
    help=f"JSON: {', '.join(q['dest'] for q in loop_q['questions'])}",
)
```

### AbstractWizardProvider

An `abc.ABC` (consistent with `AbstractInvoker` in `wt-invokers`). Provides a concrete generic `input_generator()` that subclasses inherit. Abstract methods must be overridden.

```python
class AbstractWizardProvider(ABC):
    def __init__(self) -> None:
        self._answers: dict[str, Any] = {}

    @property
    def answers(self) -> MappingProxyType[str, Any]:
        """Read-only view of collected answers."""
        return MappingProxyType(self._answers)

    @abstractmethod
    def get_questions(self) -> list[WizardQuestion]: ...

    def _validate_answer(self, question: SingleWizardQuestion, answer: str | None) -> Generator[SingleWizardQuestion, str | None, Any]:
        """Validate/coerce answer via the question's type callable.
        Re-yields question with error on validation failure until a valid answer is received."""
        ...

    def _process_question(self, question: WizardQuestion) -> Generator[SingleWizardQuestion, str | None, Any]:
        """Process a single question or loop group, recursively via yield from."""
        ...

    def input_generator(self) -> Generator[SingleWizardQuestion, str | None, None]:
        """Generic generator loop. Iterates get_questions(), validates via type callables,
        handles re-yields on error and loop questions. Uses _process_question() with
        yield from for recursive WizardQuestionLoop support.
        Concrete — rarely needs overriding."""
        ...

    def dump(self, workdir: Path) -> None:
        """Concrete. Convention-based template rendering with MRO-based fallback.

        1. Walks the class MRO to find templates/ dirs colocated with each class.
        2. Creates a Jinja ChoiceLoader (subclass-first priority).
        3. Collects the union of all top-level *.jinja2 filenames across all loaders.
        4. Renders each template with {**self._answers, year=<current_year>}.
        5. Output filename = template filename minus .jinja2 suffix.

        This means subclasses can:
        - Override a default template by providing one with the same name
        - Add new templates for additional artifacts
        - Inherit all other default templates without copying them

        Subdirs (e.g., licenses/) are available for {% include %} lookups.
        Raises UndefinedError (from Jinja) if answers are missing."""
        ...
```

`get_questions()` is abstract. `input_generator()` and `dump()` are concrete. `answers` is a concrete read-only property. No `validate()` — generator completion guarantees completeness; `dump()` raises Jinja `UndefinedError` if answers are missing.

### Generator contract

1. Caller: `question = next(gen)` → gets first question
2. Caller: `question = gen.send(answer_str)` → sends answer, gets next question (or re-yield with `error` on validation failure)
3. Generator stores valid answers on `self._answers`
4. Generator raises `StopIteration` when all questions are answered

---

## 2. `wizard/default.py` — DefaultWizardProvider

### Architecture: Separation of questions, validation, and flow

The provider separates concerns into overridable methods, enabling extensibility:

- **`get_questions()`** — Returns the ordered list of `WizardQuestion` dicts. Each question carries validation logic in its `argparse.type` callable. Override to add, remove, reorder, or modify questions.
- **`input_generator()`** — Generic generator loop that iterates `get_questions()`, invokes each question's `type` callable for validation/coercion, and handles re-yields on error and loop questions. Rarely needs overriding.

Answers are stored internally in `self._answers: dict[str, Any]` and exposed read-only via `self.answers` property returning `MappingProxyType(self._answers)`.

This means custom providers (future work) can do:
```python
class MyProvider(DefaultWizardProvider):
    def get_questions(self):
        qs = super().get_questions()
        qs = [q for q in qs if q["dest"] != "license_type"]  # remove
        qs.insert(2, WizardQuestion(
            dest="my_field",
            argparse={"help": "My custom field", "type": non_empty_str},
            wizard={},
        ))
        return qs
```

### Questions (returned by `get_questions()`)

| # | dest | type | validation | notes |
|---|------|------|------------|-------|
| 1 | `workflow_id` | free text | Valid Python identifier, ≤64 chars, not keyword/builtin (mirrors `spec.py::_is_not_reserved` + `_is_valid_spec_name`) | Required |
| 2 | `workflow_name` | free text | Non-empty | For README title |
| 3 | `workflow_description` | free text | None (optional, defaults to `""`) | For README |
| 4 | `author_name` | free text | Non-empty | For README + LICENSE |
| 5 | `license_type` | select | Must be in choices list | Choices: `BSD-3-Clause`, `MIT`, `Apache-2.0`. Default: `BSD-3-Clause` |
| 6 | `requirements` | `WizardQuestionLoop` | See sub-questions below | Loop of structured sub-questions; collects into `self._answers["requirements"]` as list of dicts |

**Question 6 detail — `WizardQuestionLoop`:**

```python
WizardQuestionLoop(
    dest="requirements",
    questions=[
        SingleWizardQuestion(
            dest="name",
            argparse={"help": "Package name", "type": non_empty_str},
            wizard={},
        ),
        SingleWizardQuestion(
            dest="version",
            argparse={"help": "Version spec", "type": requirement_version_type, "default": "*"},
            wizard={},
        ),
        SingleWizardQuestion(
            dest="channel",
            argparse={"help": "Channel", "choices": CHANNEL_CHOICES, "default": "conda-forge"},
            wizard={},
        ),
    ],
)
```

| # | dest | type | validation | notes |
|---|------|------|------------|-------|
| 6.questions[0] | `name` | free text | `non_empty_str` | First question — empty input ends the loop |
| 6.questions[1] | `version` | free text | `requirement_version_type` — validates via `rattler.NamelessMatchSpec(value)` | Default: `"*"` |
| 6.questions[2] | `channel` | select | `choices` list built from `requirements.CHANNELS` at runtime via `_serialize_channel()` | Default: `"conda-forge"` |

Collected as `self._answers["requirements"] = [{"name": "pkg1", "version": "*", "channel": "conda-forge"}, ...]`

### Recursive `_process_question()` and `input_generator()` loop

The generator logic is split into three methods. `_validate_answer()` handles validation/coercion with re-yield on error. `_process_question()` handles a single question or loop group recursively via `yield from`. `input_generator()` iterates the top-level question list.

The generator only yields `SingleWizardQuestion` dicts to the caller (never `WizardQuestionLoop`). The loop structure is handled internally — the caller just sees a sequence of individual questions.

`yield from` propagates `send()` values through to sub-generators, so recursive nesting works correctly at arbitrary depth.

```python
def _validate_answer(self, question: SingleWizardQuestion, answer: str | None):
    """Validate/coerce answer via the question's type callable.
    Re-yields question with error on validation failure until a valid answer is received."""
    type_fn = question.get("argparse", {}).get("type", str)
    while True:
        try:
            return type_fn(answer) if answer else answer
        except (ValueError, argparse.ArgumentTypeError) as e:
            answer = yield {**question, "wizard": {**question.get("wizard", {}), "error": str(e)}}

def _process_question(self, question: WizardQuestion) -> Generator[SingleWizardQuestion, str | None, Any]:
    """Process a single question or loop group, recursively via yield from."""
    if "questions" in question:
        # WizardQuestionLoop: repeat body questions until first answer is empty.
        # Constraint: first question's type callable must reject empty/None,
        # so empty/None unambiguously signals loop termination.
        results = []
        first_q = question["questions"][0]
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
        answer = yield question
        coerced = yield from self._validate_answer(question, answer)
        return coerced or question.get("argparse", {}).get("default")

def input_generator(self) -> Generator[SingleWizardQuestion, str | None, None]:
    for question in self.get_questions():
        # Condition check — works for both SingleWizardQuestion and WizardQuestionLoop
        if "wizard" in question:
            condition = question["wizard"].get("condition")
        elif "condition" in question:
            condition = question["condition"]
        else:
            condition = None
        if condition and not condition(self.answers):
            continue
        result = yield from self._process_question(question)
        self._answers[question["dest"]] = result
```

### Validation via `argparse.type` callables

Validation is done through argparse-idiomatic `type` callables that raise `ArgumentTypeError` or `ValueError` on invalid input. The generator catches these and re-yields with the error message. Defined as standalone functions referenced in `get_questions()`:

- `workflow_id` → `workflow_id_type(value)` — raises if not identifier, >64 chars, keyword, or builtin (mirrors `spec.py` `_is_not_reserved` (lines 339–353, which calls `_is_identifier`) and `_is_valid_spec_name` (lines 372–376))
- `workflow_name`, `author_name` → `non_empty_str(value)` — raises if empty/whitespace
- `license_type` → argparse handles via `choices` list (no custom type needed)
- `workflow_description` → `type=str` (optional, no validation)

New validation callables for requirements loop (in `default.py`):

```python
from rattler import NamelessMatchSpec
from wt_compiler.requirements import CHANNELS, _serialize_channel

def requirement_version_type(value: str) -> str:
    """Validate a version string as a NamelessMatchSpec."""
    NamelessMatchSpec(value)  # raises ValueError if invalid
    return value

CHANNEL_CHOICES: list[str] = [_serialize_channel(c) for c in CHANNELS]
```

- `requirement_version_type(value)` — validates via `rattler.NamelessMatchSpec(value)`, raises `ValueError` on invalid input
- `CHANNEL_CHOICES` — channel choices list built from `requirements.CHANNELS` via `_serialize_channel()`; validated by argparse `choices`

### `.dump(workdir)` method (inherited from ABC)

Inherited concrete `dump()` scans `wt_compiler/wizard/templates/` for top-level `*.jinja2` files, renders each with `{**self._answers, year=<current_year>}`, and writes to `workdir/`. Template naming conventions: Uses `jinja2.Environment` with `PackageLoader` pointing to `wt_compiler.wizard.templates`.

| File | Template | Template variables |
|------|----------|--------------------|
| `spec.yaml` | `spec.yaml.jinja2` | `workflow_id`, `requirements` (list of dicts with `name`/`version`/`channel`) |
| `test-cases.yaml` | `test-cases.yaml.jinja2` | `workflow_id` |
| `README.md` | `README.md.jinja2` | `workflow_name`, `workflow_description`, `author_name`, `license_type` |
| `LICENSE` | `LICENSE.jinja2` (uses `{% include "licenses/" ~ license_type ~ ".txt" %}`) | `author_name`, `year`, `license_type` |
| `.gitignore` | `.gitignore.jinja2` | (none currently, but templated for future extensibility) |
| `.gitattributes` | `.gitattributes.jinja2` | (static content, templated for consistency) |

#### Template contents

**`spec.yaml.jinja2`**:
```yaml
id: {{ workflow_id }}
requirements:
{% for req in requirements %}
  - name: "{{ req.name }}"
    version: "{{ req.version }}"
    channel: "{{ req.channel }}"
{% endfor %}
{% if not requirements %}
  []
{% endif %}
workflow: []
```

**`test-cases.yaml.jinja2`**:
```yaml
# Test cases for {{ workflow_id }}
# Each top-level key is a test case name. Fields per case:
#   name: str                  - Human-readable name
#   description: str           - What the test case covers
#   params: dict               - Workflow parameters
#   raises: bool               - Whether an error is expected (default: false)
#   expected_status_code: int  - Expected HTTP status (default: 200)
#
# Example:
# my-test-case:
#   name: My Test Case
#   description: Tests the default workflow behavior
#   params:
#     param_name: value
#   raises: false
#   expected_status_code: 200
```

**`README.md.jinja2`**:
```markdown
# {{ workflow_name }}

{{ workflow_description }}

## Author

{{ author_name }}

## License

{{ license_type }}
```

**`LICENSE.jinja2`**:
```
{% include "licenses/" ~ license_type ~ ".txt" %}
```

**`.gitignore.jinja2`**:
```
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
.eggs/
*.egg
.venv/
venv/

# Pixi
.pixi/
pixi.lock
```

**`.gitattributes.jinja2`**:
```
*-*-workflow/** linguist-generated=true
```

**`licenses/*.txt`**: Standard license texts with `{{ year }}` and `{{ author_name }}` Jinja variables. One file per supported license (BSD-3-Clause, MIT, Apache-2.0). These are partials included by `LICENSE.jinja2`, not rendered directly by `dump()`.

---

## 3. `wizard/__init__.py`

```python
from wt_compiler.wizard.abstract import (
    AbstractWizardProvider,
    ArgparseKwargs,
    SingleWizardQuestion,
    WizardKwargs,
    WizardQuestion,
    WizardQuestionLoop,
    with_condition,
)
from wt_compiler.wizard.default import DefaultWizardProvider

__all__ = [
    "AbstractWizardProvider",
    "ArgparseKwargs",
    "DefaultWizardProvider",
    "SingleWizardQuestion",
    "WizardKwargs",
    "WizardQuestion",
    "WizardQuestionLoop",
    "with_condition",
]
```

---

## 4. `wizard/README.md` — Implementor Guide

A README within the wizard directory focused on what custom provider implementors need to know. Contents:

### Overview
- What the wizard system does (interactive project scaffolding)
- Relationship between `AbstractWizardProvider`, `DefaultWizardProvider`, and custom providers

### Creating a Custom Provider
- Subclass `DefaultWizardProvider` (not `AbstractWizardProvider` directly, unless starting from scratch)
- Override `get_questions()` to customize the question flow
- Add a colocated `templates/` directory with Jinja2 templates for your artifacts

### Customizing Questions
- **Add a question**: `super().get_questions()` + `list.insert()`
- **Remove a question**: filter by `dest`
- **Modify a question**: find by `dest`, update fields
- **Reorder**: rearrange the list

### WizardQuestion Structure

`WizardQuestion = SingleWizardQuestion | WizardQuestionLoop`

**`SingleWizardQuestion`:**
- `dest`: answer key, also used as argparse flag name
- `argparse`: dict of kwargs for `argparse.add_argument()` — `type`, `choices`, `help`, `default`, etc.
- `wizard`: dict of wizard-specific metadata — `condition`, `error`
- The `argparse.type` callable serves dual duty: coercion AND validation (raise `ArgumentTypeError` on invalid input)

**`WizardQuestionLoop`:**
- `dest`: key for the collected list (e.g., `"requirements"`)
- `questions`: list of `WizardQuestion` (sub-questions asked per iteration; recursive nesting supported)
- `condition`: optional gate to skip the entire loop
- Termination: empty/None answer on first sub-question ends the loop
- Argparse: auto-derived `--{dest}` with `action="append"` and composite JSON type validator

### Conditional Questions
- Add `condition: Callable[[MappingProxyType], bool]` to `wizard` dict
- The generator skips questions where `condition(answers)` returns `False`
- Order questions so dependencies come first
- For mutually exclusive branches: use mutually exclusive conditions on each branch's questions

### Composing Question Branches

Use `with_condition(questions, condition)` to apply a condition gate to an entire branch:

```python
def with_condition(
    questions: list[WizardQuestion],
    condition: Callable[[MappingProxyType[str, Any]], bool],
) -> list[WizardQuestion]:
    """Apply a condition gate to all questions in a branch.

    Handles both SingleWizardQuestion (sets wizard.condition)
    and WizardQuestionLoop (sets top-level condition)."""
    result = []
    for q in questions:
        if "questions" in q:  # WizardQuestionLoop
            result.append({**q, "condition": condition})
        else:  # SingleWizardQuestion
            result.append({**q, "wizard": {**q.get("wizard", {}), "condition": condition}})
    return result
```

Example usage:

```python
from wt_compiler.wizard import DefaultWizardProvider, WizardQuestion, with_condition

gcp_questions = [
    WizardQuestion(dest="gcp_project", argparse={"help": "GCP project ID", "type": str}, wizard={}),
    WizardQuestion(dest="gcp_region", argparse={"help": "GCP region", "type": str, "default": "us-central1"}, wizard={}),
]

local_questions = [
    WizardQuestion(dest="local_path", argparse={"help": "Local output path", "type": str}, wizard={}),
]

class MyProvider(DefaultWizardProvider):
    def get_questions(self):
        common = super().get_questions()
        # Insert a variant selector after the common questions
        common.append(WizardQuestion(
            dest="variant",
            argparse={"help": "Platform variant", "type": str, "choices": ["gcp", "local"]},
            wizard={},
        ))
        return (
            common
            + with_condition(gcp_questions, lambda a: a.get("variant") == "gcp")
            + with_condition(local_questions, lambda a: a.get("variant") == "local")
        )
```

### Custom Templates
- Place `*.jinja2` files in a `templates/` dir colocated with your provider module
- `dump()` uses MRO-based template resolution (subclass templates override parent templates)
- To override a default template: provide a file with the same name in your `templates/` dir
- To add a new artifact: add a new `.jinja2` file — it will be rendered alongside the defaults
- All other default templates are inherited without copying
- Output filename = template filename minus `.jinja2` suffix
- Subdirectories are available for `{% include %}` (e.g., `licenses/`)
- Context: all collected answers + `year` (current year)

### Dual CLI Modes
- **Interactive**: a CLI loop iterates the generator, prompts via `input()`, sends answers via `.send()`
- **Batch/static**: each question's `argparse` dict defines CLI flags like `--workflow-id VALUE`
- Both modes use the same question definitions

---

## 5. Tests

### `test_wizard_abstract.py` — ABC conformance & generator mechanics

- `test_default_provider_is_subclass`: `issubclass(DefaultWizardProvider, AbstractWizardProvider)` is `True`
- `test_abstract_methods_enforced`: Attempting to instantiate `AbstractWizardProvider` directly raises `TypeError`
- `test_input_generator_yields_dicts_with_required_keys`: Every yielded dict has `dest` (str) and `argparse` (dict with `help`)
- `test_argparse_compatibility`: For each yielded question, pass `question["argparse"]` as `**kwargs` to `argparse.ArgumentParser().add_argument(f"--{dest.replace('_', '-')}", ...)` — no errors raised
- `test_send_based_flow_complete`: Drive generator with valid answers, verify `StopIteration` and `provider.answers` fully populated
- `test_invalid_answer_reyields_with_error`: Send invalid workflow_id, verify re-yielded dict has `question["wizard"]["error"]` set

### `test_wizard_default.py` — DefaultWizardProvider behavior

- `test_workflow_id_validation_*`: Test each validation case via `_validate_workflow_id` — valid, not identifier, too long, keyword, builtin, empty
- `test_requirements_loop_multiple`: Drive name + version + channel per iteration for 3 requirements, then send empty on next `name` prompt → `answers["requirements"]` is a list of 3 dicts, each with `name`/`version`/`channel` keys
- `test_requirements_loop_empty_immediately`: Send empty on first `name` prompt → `answers["requirements"]` is empty list
- `test_requirement_version_validation`: Send invalid version string for `version` sub-question, verify re-yield with error from `rattler.NamelessMatchSpec`
- `test_requirement_channel_choices`: Verify the channel sub-question's `choices` list matches all channels from `requirements.CHANNELS` via `_serialize_channel()`
- `test_license_default`: Send `None`/empty for license → defaults to `BSD-3-Clause`
- `test_license_invalid_choice_reyields`: Send invalid string → re-yield with error
- `test_dump_creates_all_files` (uses `tmp_path`): All 6 files exist after dump
- `test_dump_spec_yaml_valid_structure`: Parse generated spec.yaml, verify `id`, `requirements`, `workflow` keys; verify each requirement has `name`/`version`/`channel` keys matching `SpecRequirement` format
- `test_dump_test_cases_yaml_structure`: Verify it's valid commented YAML
- `test_dump_readme_contains_metadata`: Verify workflow name, description, author present
- `test_dump_gitignore_contents`: Has `__pycache__/`, `.pixi/`
- `test_dump_gitattributes_contents`: Has `linguist-generated=true`
- `test_dump_raises_on_incomplete_answers`: Incomplete provider (generator interrupted mid-flow) → Jinja `UndefinedError` when rendering templates that reference missing answers

### `test_wizard_extensibility.py` — Extensibility & custom providers

- `test_custom_provider_is_subclass`: A subclass that overrides abstract methods is a valid `AbstractWizardProvider` subclass
- `test_override_get_questions_add_question`: Subclass adds a custom question to the list, drives wizard, verifies the custom answer is collected
- `test_override_get_questions_remove_question`: Subclass removes a default question (e.g., `license_type`), drives wizard, verifies that question is never yielded
- `test_override_get_questions_modify_question`: Subclass modifies a default question (e.g., changes `choices` for `license_type`), verifies the modified choices are yielded
- `test_override_get_questions_reorder`: Subclass reorders questions, verifies they are yielded in the new order
- `test_custom_type_callable_validation`: Subclass adds a question with a custom `type` callable that raises `ArgumentTypeError`, verifies re-yield with error
- `test_conditional_question_asked_when_condition_true`: Subclass adds a question with `condition: lambda a: a.get("workflow_id", "").startswith("test_")`. Drive wizard with `workflow_id="test_foo"`, verify the conditional question is yielded.
- `test_conditional_question_skipped_when_condition_false`: Same setup, drive with `workflow_id="my_wf"`, verify the conditional question is NOT yielded.
- `test_mutually_exclusive_branches`: Subclass adds two sets of questions with mutually exclusive conditions (e.g., `variant == "gcp"` vs `variant == "local"`). Drive with each variant value, verify only the correct branch's questions are asked.
- `test_condition_inspects_answers_proxy`: Verify that the `condition` callable receives the read-only `MappingProxyType` (not the mutable `_answers` dict).
- `test_with_condition_composes_branches`: Use `with_condition()` to compose two question branches with mutually exclusive conditions. Drive wizard with each variant, verify correct branch is followed. Verify `with_condition()` handles both `SingleWizardQuestion` (sets `wizard.condition`) and `WizardQuestionLoop` (sets top-level `condition`).
- `test_custom_template_overrides_default`: Subclass provides a `templates/spec.yaml.jinja2` with different content. Verify the overridden template is rendered instead of the default.
- `test_custom_template_adds_new_artifact`: Subclass provides a `templates/extra.yaml.jinja2`. Verify the new artifact is rendered alongside all default artifacts.
- `test_default_templates_inherited`: Subclass provides only one custom template. Verify all other default templates are still rendered.

### `test_wizard_cli_compat.py` — CLI compatibility for interactive & static modes

**Interactive mode tests** (simulate `input()` loop):
- `test_interactive_loop_drives_generator`: Simulate an interactive session by monkeypatching `builtins.input` with a sequence of answers. A helper function iterates the generator, calling `input(question["argparse"]["help"])` for each question and sending answers via `.send()`. Verify the wizard completes and all answers are collected.
- `test_interactive_loop_displays_choices`: For select-type questions (with `choices`), verify the interactive helper formats and displays the choices to the user before calling `input()`.
- `test_interactive_loop_redisplays_on_error`: When `type` callable raises, verify the interactive loop displays the error message and re-prompts (same question yielded again with `wizard.error`).
- `test_interactive_loop_handles_loop_question`: For the requirements loop question, verify the interactive loop keeps prompting until empty input.

**Static/batch mode tests** (argparse flags):
- `test_argparse_add_argument_compatibility`: For each question from `get_questions()`, verify that `parser.add_argument(f"--{dest.replace('_', '-')}", **question["argparse"])` succeeds without error.
- `test_argparse_parse_args_valid`: Build an argparse parser from all questions, parse a valid set of args (e.g., `['--workflow-id', 'my_wf', '--workflow-name', 'My Workflow', ...]`), verify namespace has correct values.
- `test_argparse_parse_args_with_type_validation`: Build parser, parse args with invalid `workflow_id` (e.g., `123bad`), verify argparse raises `SystemExit` (its standard error behavior for invalid `type`).
- `test_argparse_to_generator_bridge`: Given a parsed argparse `Namespace`, feed its values into the generator via `.send()` in order, verify the wizard completes with the same answers. For loop questions, the bridge feeds JSON dict fields into the generator as individual sub-question answers.
- `test_loop_question_argparse_json_append`: For the requirements `WizardQuestionLoop`, verify auto-derived argparse uses `action="append"` with a composite JSON `type` validator built from sub-questions' `type`/`choices`. Batch mode usage: `--requirements '{"name": "pkg1", "version": "*", "channel": "conda-forge"}' --requirements '{"name": "pkg2", ...}'`. Verify the type validator rejects invalid JSON, missing fields, and invalid sub-field values.

### Test helper

```python
def drive_wizard(provider: DefaultWizardProvider, answers: list[str]) -> list[dict]:
    """Drive wizard generator with a sequence of answers. Returns all yielded questions."""
```

---

## 6. Verification

1. **Unit tests**: `uv run pytest wt-compiler/tests/test_wizard_abstract.py wt-compiler/tests/test_wizard_default.py wt-compiler/tests/test_wizard_extensibility.py wt-compiler/tests/test_wizard_cli_compat.py -v`
2. **Type checking**: `uv run mypy wt-compiler/src/wt_compiler/wizard/`
3. **Linting**: `uv run ruff check wt-compiler/src/wt_compiler/wizard/`
4. **Formatting**: `uv run ruff format wt-compiler/src/wt_compiler/wizard/`
5. **Existing tests still pass**: `uv run pytest wt-compiler/tests/ -v`
