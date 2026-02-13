"""Command-line interface for wt-compiler."""

import argparse
import asyncio
import resource
import sys
from pathlib import Path
from typing import Any

from wt_compiler.compiler import compile_workflow_from_yaml


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

    args = parser.parse_args()

    if args.command == "compile":
        _compile(args)


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
