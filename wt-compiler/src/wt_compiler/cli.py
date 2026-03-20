"""Command-line interface for wt-compiler."""

from __future__ import annotations

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
                sys.exit(1)
            try:
                answer = next(answer_iter)
            except StopIteration:
                print(
                    "Error: --no-interactive answer sequence exhausted before wizard completed.",
                    file=sys.stderr,
                )
                sys.exit(1)
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
    - ``iteration > 0``: "Add another {dest}?" (default True)
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
                confirmed = questionary.confirm(confirm_msg, default=True).ask()
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
    # Phase 1: pre-parse to detect --provider before building the full parser.
    # We need the provider name up front so its questions can be added to
    # init_parser as proper argparse flags (enabling --no-interactive batch
    # mode with any provider).  A dedicated flag works cleanly with
    # parse_known_args(); subparser positionals do not.
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument(
        "--provider",
        default=None,
        metavar="PROVIDER",
        help=(
            "Name of a registered wizard provider. "
            "Omit to use the built-in DefaultWizardProvider. "
            "Custom providers must include a 'workflow_id' answer to name the output directory."
        ),
    )
    pre_parser.add_argument(
        "--no-interactive",
        action="store_true",
        help=(
            "Run in batch mode using CLI flags instead of interactive prompts. "
            "Required flags depend on the selected provider's questions."
        ),
    )
    pre_args, extras = pre_parser.parse_known_args()
    provider_name: str | None = pre_args.provider
    is_init = bool(extras and extras[0] == "init")

    if (
        provider_name is None
        and is_init
        and not pre_args.no_interactive
        and "--help" not in extras
        and "-h" not in extras
    ):
        import wt_compiler.providers as providers_mod

        try:
            registered = providers_mod.get_registered_providers()
        except (ValueError, PermissionError):
            registered = []
        if registered:
            choices = ["default"] + [e["name"] for e in registered]
            selected = questionary.select(
                "Select a wizard provider:",
                choices=choices,
                default="default",
            ).ask()
            if selected is None:
                sys.exit(1)  # Ctrl+C
            if selected != "default":
                provider_name = selected

    wizard: AbstractWizardProvider
    if provider_name is not None:
        import wt_compiler.providers as providers_mod

        try:
            provider_cls = providers_mod.load_provider_class(provider_name)
        except (ValueError, TypeError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        try:
            wizard = provider_cls()
        except Exception as e:
            print(
                f"Error initializing provider {provider_name!r}: {e}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        wizard = DefaultWizardProvider()
    init_questions = wizard.get_questions()

    # Phase 2: build the full parser using the resolved provider's questions.
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

    # init subcommand  (init_questions and wizard were resolved in phase 1 above)
    # _pre is passed as parent so --provider and --no-interactive are inherited,
    # keeping their definitions in a single place.
    init_parser = subparsers.add_parser(
        "init",
        help="Scaffold a new workflow project directory",
        description=(
            "Interactively scaffold a new workflow project. "
            "Use --no-interactive with --workflow-id, --workflow-name, and --author-name "
            "to run in batch mode."
        ),
        parents=[pre_parser],
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
    for q in init_questions:
        flag = "--" + q["dest"].replace("_", "-")
        ap_kwargs: Any = {**cast(SingleWizardQuestion, q)["argparse"]}
        init_parser.add_argument(flag, **ap_kwargs)

    reg_parser = subparsers.add_parser(
        "register-provider",
        help="Install and register a wizard provider package",
        description=(
            "Install a Python package and register all wt_compiler.wizard_providers "
            "entry points it exposes. The package must be available on PyPI or in your "
            "conda channels. Note: all registered providers must expose a 'workflow_id' "
            "answer key for the init command to derive the output directory name."
        ),
    )
    reg_parser.add_argument(
        "package",
        metavar="PACKAGE",
        help="Package name to install and register (e.g. my-wt-provider)",
    )
    subparsers.add_parser(
        "list-providers",
        help="List all registered wizard providers",
        description="Show all wizard providers registered via 'wt-compiler register-provider'.",
    )

    args = parser.parse_args()

    if args.command == "compile":
        _compile(args)
    elif args.command == "init":
        _init(args, wizard)
    elif args.command == "register-provider":
        _register_provider(args)
    elif args.command == "list-providers":
        _list_providers()
    else:
        raise AssertionError(f"Unhandled command: {args.command!r}")


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


def _finalize_init(provider: AbstractWizardProvider, args: argparse.Namespace) -> None:
    """Finalize the init command by writing project artifacts to disk.

    Derives the output directory from provider answers and CLI flags,
    validates the ``workflow_id`` answer, and delegates to
    ``provider.dump()``.

    Args:
        provider: Completed wizard provider with ``workflow_id`` in answers.
        args: Parsed CLI arguments (``output_dir``, ``clobber``).

    Raises:
        ValueError: If ``workflow_id`` is missing or empty in provider answers.
        FileExistsError: If the output directory exists and ``--clobber`` is not set.
        RuntimeError: If ``provider.dump()`` fails (e.g., no templates found).
    """
    output_dir = args.output_dir if args.output_dir is not None else Path.cwd()
    workdir_name = provider.answers.get("workflow_id")
    if not workdir_name:
        raise ValueError(
            "Provider answers must include 'workflow_id' to determine the output directory name."
        )
    workdir_path = Path(workdir_name)
    if workdir_path.is_absolute() or workdir_path.name != workdir_name:
        raise ValueError(
            f"'workflow_id' must be a simple directory name with no path separators, "
            f"got {workdir_name!r}."
        )
    workdir = output_dir / workdir_name
    if workdir.exists() and not args.clobber:
        raise FileExistsError(f"Output directory already exists: {workdir}")
    provider.dump(workdir)
    print(f"Initialized workflow project at: {workdir}")


def _init(args: argparse.Namespace, provider: AbstractWizardProvider) -> None:
    """Execute the init command.

    Scaffolds a new workflow project directory. ``provider`` has already been
    resolved and instantiated by ``main()`` (default or custom), so this
    function only dispatches to ``_batch_init`` or ``_interactive_init``.

    Args:
        args: Parsed command-line arguments.
        provider: Wizard provider instance (default or custom, pre-resolved).
    """
    if args.no_interactive:
        _batch_init(provider, args, provider.get_questions())
        try:
            _finalize_init(provider, args)
        except FileExistsError as e:
            print(f"Error: {e}", file=sys.stderr)
            print("Use --clobber to overwrite existing directory", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            _interactive_init(provider)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        try:
            _finalize_init(provider, args)
        except FileExistsError as e:
            print(f"Error: {e}", file=sys.stderr)
            print("Use --clobber to overwrite existing directory", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)


def _register_provider(args: argparse.Namespace) -> None:
    """Install and register a wizard provider package.

    Installs the package using the auto-detected installer, discovers all
    ``wt_compiler.wizard_providers`` entry points, and adds new ones to the
    providers allowlist.

    Args:
        args: Parsed CLI arguments (``package`` field).
    """
    import subprocess
    from importlib.metadata import PackageNotFoundError

    import wt_compiler.providers as _providers

    try:
        new_names = _providers.install_and_register(args.package)
    except subprocess.CalledProcessError as e:
        print(f"Error: installation of '{args.package}' failed:\n{e}", file=sys.stderr)
        sys.exit(1)
    except PackageNotFoundError:
        print(
            f"Error: Package '{args.package}' not found after install attempt. "
            "Check the package name.",
            file=sys.stderr,
        )
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    if new_names:
        print(
            f"Registered {len(new_names)} provider(s) from '{args.package}': {', '.join(new_names)}"
        )
    else:
        print(f"All providers from '{args.package}' were already registered.")


def _list_providers() -> None:
    """List all registered wizard providers.

    Prints a formatted table of registered provider names and their package
    sources, or a message if no providers are registered.
    """
    import wt_compiler.providers as _providers

    try:
        providers = _providers.get_registered_providers()
    except (ValueError, PermissionError) as e:
        print(f"Error reading provider registry: {e}", file=sys.stderr)
        sys.exit(1)
    if not providers:
        print("No providers registered. Use 'wt-compiler register-provider <package>' to add one.")
        return
    print(f"{'NAME':<30}{'PACKAGE'}")
    print("─" * 54)
    for entry in providers:
        print(f"{entry['name']:<30}{entry['package']}")
