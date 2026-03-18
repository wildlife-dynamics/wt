"""Command-line interface for wt-compiler."""

import argparse
import asyncio
import resource
import sys
from pathlib import Path
from typing import Any, cast

from wt_compiler.compiler import compile_workflow_from_yaml
from wt_compiler.wizard import DefaultWizardProvider
from wt_compiler.wizard.abstract import WizardQuestionLoop, _make_loop_type
from wt_compiler.wizard.default import non_empty_str, workflow_id_type

# Module-level: build requirements argparse type for the init subparser.
# Placed outside main() so compile subcommand is unaffected if wizard
# construction ever becomes expensive, and to avoid repeated construction
# in tests that call main() multiple times.
_wt_tmp_provider = DefaultWizardProvider()
_wt_req_q = next(
    (q for q in _wt_tmp_provider.get_questions() if q["dest"] == "requirements"), None
)
if _wt_req_q is None:
    raise RuntimeError(
        "wt_compiler.cli: DefaultWizardProvider has no 'requirements' question; "
        "cannot build init subparser."
    )
_wt_req_loop_type = _make_loop_type(cast(WizardQuestionLoop, _wt_req_q)["questions"])
del _wt_tmp_provider, _wt_req_q


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
    init_parser = subparsers.add_parser(
        "init",
        help="Scaffold a new workflow project directory",
        description=(
            "Interactively scaffold a new workflow project. "
            "Pass --workflow-id, --workflow-name, and --author-name to run non-interactively."
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
        "--workflow-id",
        type=workflow_id_type,
        default=None,
        metavar="ID",
        help="Workflow ID — valid Python identifier, ≤64 chars (batch mode)",
    )
    init_parser.add_argument(
        "--workflow-name",
        type=non_empty_str,
        default=None,
        metavar="NAME",
        help="Workflow name, human-readable (batch mode)",
    )
    init_parser.add_argument(
        "--workflow-description",
        type=str,
        default=None,
        metavar="DESC",
        help="Workflow description, optional (batch mode)",
    )
    init_parser.add_argument(
        "--author-name",
        type=non_empty_str,
        default=None,
        metavar="AUTHOR",
        help="Author name (batch mode)",
    )
    init_parser.add_argument(
        "--license-type",
        type=str,
        choices=["BSD-3-Clause", "MIT", "Apache-2.0"],
        default=None,
        help="License type (batch mode; default: BSD-3-Clause)",
    )
    init_parser.add_argument(
        "--requirements",
        type=_wt_req_loop_type,
        action="append",
        default=None,
        metavar="JSON",
        help=(
            "Conda requirement as JSON object: "
            '\'{"name":"pkg","version":"*","channel":"conda-forge"}\' '
            "(batch mode; repeatable)"
        ),
    )

    args = parser.parse_args()

    if args.command == "compile":
        _compile(args)
    elif args.command == "init":
        _init(args)


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


def _init(args: argparse.Namespace) -> None:
    """
    Execute the init command.

    Scaffolds a new workflow project directory by driving DefaultWizardProvider
    either interactively (input() prompts) or in batch mode (CLI flags).
    Batch mode activates when --workflow-id, --workflow-name, and --author-name
    are all provided. Providing any batch flag without all three required flags
    is an error.

    Args:
        args: Parsed command-line arguments.
    """
    provider = DefaultWizardProvider()

    # Partial batch validation: if any batch flag is provided, all required
    # ones must be present — prevents silent data loss in interactive fallback.
    _any_batch = (
        args.workflow_id is not None
        or args.workflow_name is not None
        or args.workflow_description is not None
        or args.author_name is not None
        or args.license_type is not None
        or args.requirements is not None
    )
    _required_batch = {
        "--workflow-id": args.workflow_id,
        "--workflow-name": args.workflow_name,
        "--author-name": args.author_name,
    }
    if _any_batch:
        _missing = [k for k, v in _required_batch.items() if v is None]
        if _missing:
            print(
                f"Error: partial batch flags provided. "
                f"When using batch mode, all required flags must be present. "
                f"Missing: {', '.join(_missing)}",
                file=sys.stderr,
            )
            sys.exit(1)

    batch_mode = (
        args.workflow_id is not None
        and args.workflow_name is not None
        and args.author_name is not None
    )

    if batch_mode:
        provider._answers["workflow_id"] = args.workflow_id
        provider._answers["workflow_name"] = args.workflow_name
        provider._answers["workflow_description"] = (
            args.workflow_description if args.workflow_description is not None else ""
        )
        provider._answers["author_name"] = args.author_name
        provider._answers["license_type"] = (
            args.license_type if args.license_type is not None else "BSD-3-Clause"
        )
        provider._answers["requirements"] = (
            args.requirements if args.requirements is not None else []
        )
    else:
        gen = provider.input_generator()
        try:
            question = next(gen)
            while True:
                error = question.get("wizard", {}).get("error")
                if error:
                    print(f"Error: {error}", file=sys.stderr)
                choices = question["argparse"].get("choices")
                if choices:
                    print(f"Choices: {', '.join(choices)}")
                prompt = question["argparse"].get("help", question["dest"])
                answer = input(f"{prompt}: ")
                # Pre-validate choices before sending to generator to avoid
                # ValueError from input_generator's choices check (which does
                # not re-yield — it raises, terminating the generator).
                if choices and answer not in choices:
                    print(
                        f"Error: '{answer}' is not a valid choice. "
                        f"Choose from: {', '.join(choices)}",
                        file=sys.stderr,
                    )
                    continue
                question = gen.send(answer)
        except StopIteration:
            pass
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

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
