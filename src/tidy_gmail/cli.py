"""cli.py - command line interface.

uvx tidy-gmail init
uvx tidy-gmail doctor
uvx tidy-gmail scan
uvx tidy-gmail report
uvx tidy-gmail candidates
uvx tidy-gmail trash
uvx tidy-gmail restore
"""

import argparse
from pathlib import Path
import sqlite3
import sys

from . import gmail_client as gmail  # noqa: F401
from . import storage
from .classify import select_candidates  # noqa: F401
from .cleanup import confirm, trash  # noqa: F401
from .inventory import read_inventory, scan  # noqa: F401
from .reports import candidates, report
from .restore import restorable, restore  # noqa: F401
from .rules import (
    Settings,
    load_settings,
    sender_rules,
)

APP_NAME = "tidy-gmail"


def prepare(
    root: Path,
) -> tuple[Settings, set[str], dict[str, str]]:
    """Validate the existing workspace without repairing it."""
    storage.check_repos_case(root)

    for name in ("data", "output", ".local"):
        if not (root / name).is_dir():
            raise FileNotFoundError(f"Missing {root / name}; run tidy-gmail init")

    settings = load_settings(root / "data" / "config.toml")

    protected, decisions = sender_rules(root / "data")

    return settings, protected, decisions


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser and register every command."""
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Conservative Gmail cleanup",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="tidy-gmail 0.1.0",
    )

    parser.add_argument(
        "--workspace", type=Path, help="Use an existing local workspace"
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    init_parser = sub.add_parser(
        "init",
        help=("Create the local workspace without overwriting existing files"),
    )

    init_parser.add_argument(
        "--yes",
        action="store_true",
        help="Create only missing files without a prompt",
    )

    sub.add_parser(
        "doctor",
        help="Validate the local configuration",
    )

    scan_parser = sub.add_parser(
        "scan",
        help="Fetch Gmail metadata and discover senders",
    )

    scan_parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum additional unique messages this invocation (automatically resumes)",
    )

    scan_parser.add_argument(
        "--restart",
        action="store_true",
        help="Archive previous results and begin a fresh scan",
    )

    sub.add_parser(
        "report",
        help="Show sender counts and candidate totals",
    )

    sub.add_parser(
        "candidates",
        help="Save candidate CSV without Gmail modifications",
    )

    for command in ("trash", "restore"):
        command_parser = sub.add_parser(
            command,
            help=f"{command.title()} logged Gmail messages",
        )

        command_parser.add_argument(
            "--limit",
            type=int,
            default=None,
        )

        command_parser.add_argument(
            "--execute",
            action="store_true",
            help="Request actual mailbox modification",
        )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute the requested CLI command."""
    args = build_parser().parse_args(argv)
    root = (
        args.workspace.expanduser().resolve() if args.workspace else storage.workspace()
    )

    try:
        if args.command == "init":
            storage.init(
                root,
                confirm=args.yes,
            )
            return 0

        settings, protected, decisions = prepare(root)

        if args.command == "doctor":
            print(f"Workspace valid: {root}")
            print("OAuth not tested; no Gmail connection made")

        elif args.command == "scan":
            scan(
                root,
                settings,
                limit=args.limit,
                restart=args.restart,
            )

        elif args.command == "report":
            report(
                root,
                settings,
                protected,
                decisions,
            )

        elif args.command == "candidates":
            candidates(
                root,
                settings,
                protected,
                decisions,
            )

        elif args.command == "trash":
            trash(
                root,
                settings,
                protected,
                decisions,
                execute=args.execute,
                limit=settings.batch_size if args.limit is None else args.limit,
            )

        elif args.command == "restore":
            restore(
                root,
                execute=args.execute and not settings.dry_run,
                limit=settings.batch_size if args.limit is None else args.limit,
            )

    except KeyboardInterrupt:
        print(
            "Interrupted. Completed scan work is saved; run scan again to resume.",
            file=sys.stderr,
        )
        return 130
    except (
        sqlite3.Error,
        OSError,
        ValueError,
        KeyError,
        EOFError,
    ) as exc:
        print(
            f"Error: {exc}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
