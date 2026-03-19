"""Command-line interface for wt-compiler."""

import argparse
import asyncio
import resource
import sys
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeGuard, cast

import questionary

from wt_compiler.compiler import compile_workflow_from_yaml
from wt_compiler.wizard import DefaultWizardProvider
from wt_compiler.wizard.abstract import (
    AbstractWizardProvider,
    LoopContext,
    SingleWizardQuestion,
    WizardQuestion,
    WizardQuestionLoop,
)


def _is_loop(q: WizardQuestion) -> TypeGuard[WizardQuestionLoop]:
    """Runtime type guard: ``True`` if *q* is a ``WizardQuestionLoop``."""
    return "questions" in q


def _make_questionary_validator(
    type_fn: Callable[[str], Any],
) -> Callable[[str], bool | str]:
    """Wrap an argparse type callable into a questionary validate function.

    questionary's ``validate`` parameter expects a callable that returns
    ``True`` on success or an error string on failure.

    Args:
        type_fn: An argparse-style type callable that raises
            ``argparse.ArgumentTypeError`` or ``ValueError`` on invalid input.

    Returns:
        A callable suitable for ``questionary.text(validate=...)``.
    """

    def validator(answer: str) -> bool | str:
        try:
            type_fn(answer)
            return True
        except (argparse.ArgumentTypeError, ValueError) as e:
            return str(e)

    return validator


def _batch_init(
    provider: AbstractWizardProvider,
    args: argparse.Namespace,
    questions: list[WizardQuestion],
) -> None:
    """Drive the wizard provider in batch mode from pre-parsed CLI flags.

    Validates that all required fields (those with no default in the question
    definition) are present, builds a flat answer sequence from ``args``, then
    drives the generator to completion.

    Args:
        provider: A wizard provider instance (``AbstractWizardProvider``).
        args: Parsed CLI namespace; wizard flag values are read from here.
        questions: Ordered question list used to build the answer sequence.

    Raises:
        SystemExit: If required flags are missing or the generator raises.
    """
    missing = [
        f"--{q['dest'].replace('_', '-')}"
        for q in questions
        if not _is_loop(q)
        and "default" not in cast(SingleWizardQuestion, q)["argparse"]
        and getattr(args, q["dest"]) is None
    ]
    if missing:
        print(f"Error: --no-interactive requires: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    # Build flat answer sequence in generator-expected order.
    # Single questions → one string; loop questions → one string per sub-field
    # per item (respecting wizard.condition gates), then "" to signal loop end.
    seq: list[str] = []
    for q in questions:
        if _is_loop(q):
            for item in getattr(args, q["dest"]) or []:
                partial_entry: dict[str, Any] = {}
                for i, sub_q in enumerate(q["questions"]):
                    sq = cast(SingleWizardQuestion, sub_q)
                    if i > 0:  # first sub-question is the loop terminator, never conditional
                        cond = sq.get("wizard", {}).get("condition")
                        if cond and not cond(MappingProxyType(partial_entry)):
                            continue  # skip to match generator's condition logic
                    v = item.get(sq["dest"])
                    partial_entry[sq["dest"]] = v
                    seq.append(
                        str(v) if v is not None else str(sq["argparse"].get("default") or "")
                    )
            seq.append("")  # signal loop end
        else:
            sq = cast(SingleWizardQuestion, q)
            v = getattr(args, q["dest"])
            seq.append(str(v) if v is not None else str(sq["argparse"].get("default") or ""))

    answer_iter = iter(seq)
    gen = provider.input_generator()
    try:
        question = next(gen)
        while True:
            error = question.get("wizard", {}).get("error")
            if error:
                print(f"Error: {error}", file=sys.stderr)
            answer = next(answer_iter)
            question = gen.send(answer)
    except StopIteration:
        pass
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _interactive_init(provider: AbstractWizardProvider) -> None:
    """Drive the wizard provider interactively using questionary prompts.

    Replaces the raw ``input()`` loop with rich terminal widgets:
    - ``questionary.text()`` for free-text fields, with inline validation
    - ``questionary.select()`` for choice fields (arrow-key navigation)
    - ``questionary.confirm()`` for loop iteration control

    Loop boundaries are detected via ``wizard.loop_context`` injected by
    ``_process_question()``. When ``loop_context`` is present on a yielded
    question, a confirm prompt is shown before the question itself:
    - ``iteration == 0``: "Add a {dest}?" (default True)
    - ``iteration > 0``: "Add another {dest}?" (default False)
    If the user declines, ``""`` is sent to the generator to end the loop.

    Args:
        provider: A wizard provider instance (``AbstractWizardProvider``).
            Answers are stored on ``provider._answers`` by the generator.

    Raises:
        SystemExit: On questionary cancellation (Ctrl+C) or unexpected
            generator error.
    """
    gen = provider.input_generator()
    try:
        question = next(gen)
        while True:
            wizard_meta = question.get("wizard", {})

            # --- Display any validation error from the generator ---
            error: str | None = wizard_meta.get("error")
            if error:
                print(f"Error: {error}", file=sys.stderr)

            # --- Loop boundary detection ---
            loop_ctx: LoopContext | None = wizard_meta.get("loop_context")
            if loop_ctx is not None:
                is_first = loop_ctx["iteration"] == 0
                confirm_msg = (
                    f"Add a {loop_ctx['dest']}?" if is_first else f"Add another {loop_ctx['dest']}?"
                )
                confirmed = questionary.confirm(confirm_msg, default=is_first).ask()
                if confirmed is None:
                    # Ctrl+C
                    sys.exit(1)
                if not confirmed:
                    question = gen.send("")
                    continue

            choices = question["argparse"].get("choices")
            default = question["argparse"].get("default")
            prompt = question["argparse"].get("help", question["dest"])
            type_fn = question["argparse"].get("type")

            if choices:
                answer = questionary.select(
                    prompt,
                    choices=choices,
                    default=default if default in choices else choices[0],
                ).ask()
            else:
                validate_fn = _make_questionary_validator(type_fn) if type_fn else None
                answer = questionary.text(
                    prompt,
                    default=str(default) if default is not None else "",
                    validate=validate_fn,
                ).ask()

            if answer is None:
                # Ctrl+C
                sys.exit(1)

            question = gen.send(answer)

    except StopIteration:
        pass
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """
    Main CLI entry point.

    Parses command-line arguments and dispatches to the appropriate subcommand.
    Currently supports the 'compile' subcommand for compiling workflow specs.
    """
    parser = argparse.ArgumentParser(
        prog="wt-compiler",
        description="Compile workflow specifications into executable artifacts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # compile subcommand
    compile_parser = subparsers.add_parser(
        "compile",
        help="Compile a workflow spec.yaml to artifacts",
        description="Compile a workflow specification file into executable DAG artifacts, "
        "including Python code, Docker configuration, and pixi.toml.",
    )
    compile_parser.add_argument(
        "--spec",
        required=True,
        type=Path,
        metavar="FILE",
        help="Path to the workflow spec.yaml file",
    )
    compile_parser.add_argument(
        "--clobber",
        action="store_true",
        help="Overwrite existing output directory if it exists",
    )
    compile_parser.add_argument(
        "--update",
        action="store_true",
        help="Carry over lockfile from existing build and bump version",
    )
    compile_parser.add_argument(
        "--pkg-name-prefix",
        type=str,
        default="wt",
        metavar="PREFIX",
        help="Package name prefix for generated artifacts (default: wt)",
    )
    compile_parser.add_argument(
        "--install",
        action="store_true",
        help="Generate a new pixi lockfile and install all dependencies after compilation",
    )
    compile_parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable the progress spinner during compilation",
    )
    compile_parser.add_argument(
        "--variant",
        type=str,
        default=None,
        metavar="VARIANT",
        help="Platform variant suffix (e.g., 'gcp' emits wt-runner-gcp, wt-task-gcp dependencies)",
    )
    compile_parser.add_argument(
        "--results-env-var",
        type=str,
        default="WT_RESULTS",
        metavar="ENV_VAR",
        help=(
            "Name of the environment variable the generated CLI reads "
            "for the results URL (default: WT_RESULTS)"
        ),
    )

    # init subcommand
    wizard = DefaultWizardProvider()
    init_questions = wizard.get_questions()

    init_parser = subparsers.add_parser(
        "init",
        help="Scaffold a new workflow project directory",
        description=(
            "Interactively scaffold a new workflow project. "
            "Use --no-interactive with --workflow-id, --workflow-name, and --author-name "
            "to run in batch mode."
        ),
    )
    init_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="Parent directory to scaffold into (default: current directory)",
    )
    init_parser.add_argument(
        "--clobber",
        action="store_true",
        help="Overwrite existing output directory if it exists",
    )
    init_parser.add_argument(
        "--no-interactive",
        action="store_true",
        help=(
            "Run in batch mode using CLI flags. "
            "Requires --workflow-id, --workflow-name, and --author-name."
        ),
    )
    for q in init_questions:
        flag = "--" + q["dest"].replace("_", "-")
        ap_kwargs: Any = {**cast(SingleWizardQuestion, q)["argparse"]}
        init_parser.add_argument(flag, **ap_kwargs)

    args = parser.parse_args()

    if args.command == "compile":
        _compile(args)
    elif args.command == "init":
        _init(args, wizard)


def _compile(args: argparse.Namespace) -> None:
    """
    Execute the compile command.

    Args:
        args: Parsed command-line arguments containing spec path and flags.
    """
    # Increase file descriptor limit for py-rattler package extraction
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        new_soft = min(max(soft, 4096), hard)
        if new_soft > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
    except (ValueError, OSError) as e:
        print(f"Warning: Could not increase file descriptor limit: {e}", file=sys.stderr)

    if args.update and not (args.clobber and not args.install):
        print(
            "Error: --update is only valid with --clobber and without --install",
            file=sys.stderr,
        )
        sys.exit(1)

    spec_path = args.spec.resolve()

    if not spec_path.exists():
        print(f"Error: Spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    if not spec_path.is_file():
        print(f"Error: Spec path is not a file: {spec_path}", file=sys.stderr)
        sys.exit(1)

    try:
        # compile_workflow_from_yaml handles discovery automatically
        compiler_kwargs: dict[str, Any] = {
            "pkg_name_prefix": args.pkg_name_prefix,
        }
        if args.variant:
            compiler_kwargs["variant"] = args.variant
        compiler_kwargs["results_env_var"] = args.results_env_var
        artifacts = asyncio.run(
            compile_workflow_from_yaml(
                str(spec_path),
                progress=not args.no_progress,
                **compiler_kwargs,
            )
        )

        # Write artifacts to disk
        artifacts.dump(clobber=args.clobber, update=args.update)

        if args.install:
            artifacts.install()
        elif args.update:
            artifacts.update()

        print(f"Compiled workflow to: {artifacts.release_dir}")

    except FileExistsError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Use --clobber to overwrite existing directory", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _init(args: argparse.Namespace, provider: AbstractWizardProvider) -> None:
    """
    Execute the init command.

    Scaffolds a new workflow project directory. Dispatches to ``_batch_init``
    when ``--no-interactive`` is passed, otherwise to ``_interactive_init``.

    Args:
        args: Parsed command-line arguments.
        provider: Wizard provider instance to drive.
    """
    if args.no_interactive:
        _batch_init(provider, args, provider.get_questions())
    else:
        _interactive_init(provider)

    if "workflow_id" not in provider.answers:
        print("Error: wizard did not complete successfully", file=sys.stderr)
        sys.exit(1)

    output_dir = args.output_dir if args.output_dir is not None else Path.cwd()
    workdir = output_dir / provider.answers["workflow_id"]

    if workdir.exists() and not args.clobber:
        print(f"Error: Output directory already exists: {workdir}", file=sys.stderr)
        print("Use --clobber to overwrite existing directory", file=sys.stderr)
        sys.exit(1)

    try:
        provider.dump(workdir)
        print(f"Initialized workflow project at: {workdir}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
