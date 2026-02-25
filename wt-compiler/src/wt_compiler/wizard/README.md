# Wizard Provider — Implementor Guide

## Overview

The wizard system provides interactive project scaffolding for workflow projects. It consists of:

- **`AbstractWizardProvider`** — ABC defining the wizard generator protocol
- **`DefaultWizardProvider`** — Reference implementation with standard questions
- **Custom providers** — Subclass `DefaultWizardProvider` to customize

## Creating a Custom Provider

Subclass `DefaultWizardProvider` (not `AbstractWizardProvider` directly, unless starting from scratch). Override `get_questions()` to customize the question flow. Add a colocated `templates/` directory with Jinja2 templates for your artifacts.

## Customizing Questions

- **Add a question**: `super().get_questions()` + `list.insert()`
- **Remove a question**: filter by `dest`
- **Modify a question**: find by `dest`, update fields
- **Reorder**: rearrange the list

## WizardQuestion Structure

`WizardQuestion = SingleWizardQuestion | WizardQuestionLoop`

### SingleWizardQuestion

- `dest`: answer key, also used as argparse flag name
- `argparse`: dict of kwargs for `argparse.add_argument()` — `type`, `choices`, `help`, `default`, etc.
- `wizard`: dict of wizard-specific metadata — `condition`, `error`
- The `argparse.type` callable serves dual duty: coercion AND validation (raise `ArgumentTypeError` on invalid input)

### WizardQuestionLoop

- `dest`: key for the collected list (e.g., `"requirements"`)
- `questions`: list of `WizardQuestion` (sub-questions asked per iteration; recursive nesting supported)
- `condition`: optional gate to skip the entire loop
- Termination: empty/None answer on first sub-question ends the loop
- Argparse: auto-derived `--{dest}` with `action="append"` and composite JSON type validator

## Conditional Questions

- Add `condition: Callable[[MappingProxyType], bool]` to `wizard` dict
- The generator skips questions where `condition(answers)` returns `False`
- Order questions so dependencies come first
- For mutually exclusive branches: use mutually exclusive conditions on each branch's questions

## Composing Question Branches

Use `with_condition(questions, condition)` to apply a condition gate to an entire branch:

```python
from wt_compiler.wizard import DefaultWizardProvider, with_condition

gcp_questions = [
    {"dest": "gcp_project", "argparse": {"help": "GCP project ID", "type": str}, "wizard": {}},
]

local_questions = [
    {"dest": "local_path", "argparse": {"help": "Local output path", "type": str}, "wizard": {}},
]

class MyProvider(DefaultWizardProvider):
    def get_questions(self):
        common = super().get_questions()
        common.append({
            "dest": "variant",
            "argparse": {"help": "Platform variant", "type": str, "choices": ["gcp", "local"]},
            "wizard": {},
        })
        return (
            common
            + with_condition(gcp_questions, lambda a: a.get("variant") == "gcp")
            + with_condition(local_questions, lambda a: a.get("variant") == "local")
        )
```

## Custom Templates

- Place `*.jinja2` files in a `templates/` dir colocated with your provider module
- `dump()` uses MRO-based template resolution (subclass templates override parent templates)
- To override a default template: provide a file with the same name in your `templates/` dir
- To add a new artifact: add a new `.jinja2` file — it will be rendered alongside the defaults
- All other default templates are inherited without copying
- Output filename = template filename minus `.jinja2` suffix
- Subdirectories are available for `{% include %}` (e.g., `licenses/`)
- Context: all collected answers + `year` (current year)

## Dual CLI Modes

- **Interactive**: a CLI loop iterates the generator, prompts via `input()`, sends answers via `.send()`
- **Batch/static**: each question's `argparse` dict defines CLI flags like `--workflow-id VALUE`
- Both modes use the same question definitions
