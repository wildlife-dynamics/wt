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
- `argparse`: explicit kwargs for `argparse.add_argument()` — typically `action="append"` with a JSON `type` validator that parses and validates a single item dict
- Termination: empty/None answer on first sub-question ends the loop
- **Constraint**: the first sub-question must never carry a `wizard.condition`. It is the loop-termination sentinel — use the loop's own `condition` key to gate the entire loop instead.

## Conditional Questions

- Add `condition: Callable[[MappingProxyType], bool]` to `wizard` dict
- The generator skips questions where `condition(answers)` returns `False`
- Order questions so dependencies come first
- For mutually exclusive branches: use mutually exclusive conditions on each branch's questions

### Conditions inside a loop body

Sub-questions after the first in a `WizardQuestionLoop` can also carry conditions. The
condition callable receives a `MappingProxyType` of the **partial entry** collected so far
in the current iteration (not the full answers dict):

```python
WizardQuestionLoop(
    dest="requirements",
    questions=[
        SingleWizardQuestion(dest="name", ...),          # no condition — loop sentinel
        SingleWizardQuestion(dest="req_type", ...),      # no condition
        SingleWizardQuestion(dest="version", ...,        # only asked for conda
            wizard=WizardKwargs(condition=lambda e: e.get("req_type", "conda") == "conda")),
        SingleWizardQuestion(dest="path", ...,           # only asked for local path
            wizard=WizardKwargs(condition=lambda e: e.get("req_type") == "local path")),
    ],
    ...
)
```

Skipped sub-questions are absent from the entry dict — templates must handle missing keys
(e.g. with `{% if req.req_type == 'conda' %}`). Nested `WizardQuestionLoop` sub-questions
can also carry a `condition` key at the loop level.

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

## Packaging and Distributing a Custom Provider

A custom provider is just a Python package that:

1. Subclasses `DefaultWizardProvider` (or `AbstractWizardProvider`)
2. Declares a `wt_compiler.wizard_providers` entry point pointing at the class
3. Includes a `workflow_id` answer key (required by `wt-compiler scaffold init` to name the output directory)

### Entry point declaration

In your package's `pyproject.toml`:

```toml
[project.entry-points."wt_compiler.wizard_providers"]
my-provider = "my_wt_provider.provider:MyProvider"
```

The entry point name (`my-provider` above) is what users pass to `--provider`.
Each package can expose multiple entry points.

### The `workflow_id` requirement

`wt-compiler scaffold init` derives the output directory name from `provider.answers["workflow_id"]`.
Your provider **must** include a question whose `dest` is `"workflow_id"`.
`DefaultWizardProvider` already provides this — subclasses inherit it automatically.

### Installing the package

The provider must be installed into the same environment as `wt-compiler`.

**General use** — `wt-compiler` installed via `pixi global`, add the provider
to the same pixi environment:

```bash
pixi global add --environment wt-compiler my-wt-provider
```

**Local development** — `wt-compiler` invoked via `uv run`, install the
provider into the same virtual environment:

```bash
uv pip install my-wt-provider
```

Installed providers are discovered automatically via the
`wt_compiler.wizard_providers` entry point — no registration step required.
They appear in the provider selection prompt when running `wt-compiler scaffold init`
and can be selected directly with `--provider my-provider`.

### Minimal provider example

```python
# src/my_wt_provider/provider.py
from wt_compiler.wizard import DefaultWizardProvider

class MyProvider(DefaultWizardProvider):
    def get_questions(self):
        questions = super().get_questions()
        questions.append({
            "dest": "my_extra_field",
            "argparse": {"help": "Extra field", "type": str},
            "wizard": {},
        })
        return questions
```

```toml
# pyproject.toml
[project.entry-points."wt_compiler.wizard_providers"]
my-provider = "my_wt_provider.provider:MyProvider"
```

## Dual CLI Modes

- **Interactive**: a CLI loop iterates the generator, prompts via `input()`, sends answers via `.send()`
- **Batch/static**: each question's `argparse` dict defines CLI flags like `--workflow-id VALUE`
- Both modes use the same question definitions

## Rich Interactive Renderers (questionary)

The `wt-compiler scaffold init` interactive mode uses [questionary](https://github.com/tmbo/questionary)
to provide arrow-key select prompts, inline validation, and loop confirm prompts.

The generator protocol is designed to support renderers richer than a plain `input()` loop.

### Using loop_context in a renderer

When `input_generator()` is inside a `WizardQuestionLoop`, it injects `loop_context` into
the `wizard` dict of the first sub-question yield for each iteration:

```python
question["wizard"].get("loop_context")
# None on non-loop questions and on sub-questions after the first
# {"dest": "requirements", "iteration": 0}  on first entry
# {"dest": "requirements", "iteration": 1}  after one item collected
```

When `loop_context` is present, show a confirm prompt **before** rendering the question:

- `iteration == 0` → "Add a {label}?" (suggest `default=True`)
- `iteration > 0` → "Add another {label}?" (suggest `default=True`)

If the user declines, send `""` to the generator — this is the loop termination signal
(the `while answer:` guard exits the loop). The generator then yields the next top-level
question or raises `StopIteration`.

Sub-questions after the first within an iteration (e.g. `version`, `channel` in the
requirements loop) do **not** carry `loop_context` — render them unconditionally.

### Nested loops

`loop_context.iteration` resets to `0` for each new outer-loop iteration.
`_process_question()` creates a fresh local `iteration = 0` on each recursive call,
so renderers do not need to track outer-loop state to get correct inner-loop iteration counts.

### Backward compatibility

`loop_context` is an optional field (`WizardKwargs` is `total=False`). Existing `input()`
renderers that don't check for it are unaffected — the `""` termination signal still works.
