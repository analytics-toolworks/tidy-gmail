"""Local, private CSV and workspace storage."""

from collections.abc import Iterable
import csv
from datetime import UTC, datetime
import io
import os
from pathlib import Path
import tempfile

APP_NAME = "tidy-gmail"

INVENTORY_FIELDS = (
    "id",
    "thread_id",
    "sender",
    "subject",
    "internal_ms",
    "labels",
    "unsubscribe",
)

LOG_FIELDS = (
    "timestamp",
    "event",
    "id",
    "sender",
    "labels",
    "detail",
)

STARTER_FILES = {
    f"data/{name}": (Path(__file__).parent / "templates" / name).read_text(
        encoding="utf-8"
    )
    for name in (
        "config.toml",
        "senders_protected.csv",
        "sender_decisions.csv",
        "senders_always_delete.csv",
    )
}


def workspace() -> Path:
    """Use the canonical Repos convention on Windows and macOS."""
    if os.name == "nt":
        return Path("C:/Repos") / APP_NAME

    return Path.home() / "Repos" / APP_NAME


def check_repos_case(root: Path) -> None:
    """Avoid creating another Repos directory on case-sensitive systems."""
    if os.name != "nt" and root.parent.name == "Repos":
        expected = root.parent
        alternate = expected.with_name("repos")

        if not expected.exists() and alternate.exists():
            raise ValueError(
                f"Found {alternate}, expected {expected}; not creating a duplicate"
            )


def init(root: Path, *, confirm: bool = False) -> None:
    """Create only missing directories and files."""
    check_repos_case(root)

    directories = [root / name for name in ("data", "output", ".local")]

    missing_dirs = [path for path in directories if not path.is_dir()]

    missing_files = [
        root / name for name in STARTER_FILES if not (root / name).exists()
    ]

    if not missing_dirs and not missing_files:
        print(f"Already initialized: {root}")
        return

    print(f"Workspace: {root}")

    for path in (*missing_dirs, *missing_files):
        print(f"  Create: {path}")

    if not confirm:
        answer = input("Create missing items? [y/N]: ").strip().casefold()

        if answer not in {"y", "yes"}:
            print("No changes made")
            return

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    if os.name != "nt":
        (root / ".local").chmod(0o700)

    for name, content in STARTER_FILES.items():
        try:
            with (root / name).open(
                "x",
                encoding="utf-8",
                newline="",
            ) as stream:
                stream.write(content)
        except FileExistsError:
            pass

    print("Initialized. Existing files preserved. Gmail was not accessed.")


def read_csv(
    path: Path,
    fields: tuple[str, ...],
) -> list[dict[str, str]]:
    """Read generated CSV data and validate its structure."""
    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as stream:
        reader = csv.DictReader(stream)

        if reader.fieldnames != list(fields):
            raise ValueError(f"{path.name}: expected columns {', '.join(fields)}")

        rows = list(reader)

    for row in rows:
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"{path.name}: invalid CSV row")

    return rows


def write_csv(
    path: Path,
    fields: tuple[str, ...],
    rows: Iterable[dict[str, str]],
) -> None:
    """Atomically replace generated reports, never user-edited data."""
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary: str | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            prefix=".tmp-",
            suffix=".csv",
            encoding="utf-8",
            newline="",
            delete=False,
        ) as stream:
            temporary = stream.name

            writer = csv.DictWriter(
                stream,
                fieldnames=list(fields),
            )
            writer.writeheader()
            writer.writerows(rows)

            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, path)

    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def append_senders(
    path: Path,
    senders: Iterable[str],
) -> int:
    """Append unseen senders; never rewrite existing decisions."""
    from .rules import read_senders

    existing = {
        row["email"]
        for row in read_senders(
            path,
            ("email", "decision", "notes"),
        )
    }

    new = list(dict.fromkeys(sender for sender in senders if sender not in existing))

    if new:
        # REQ: Preserve existing decision bytes and commit discovery atomically.
        original = path.read_bytes()
        appended = io.StringIO(newline="")
        csv.writer(appended).writerows((sender, "", "") for sender in new)
        separator = b"" if not original or original.endswith((b"\r", b"\n")) else b"\n"
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".senders-", delete=False
            ) as stream:
                temporary = stream.name
                stream.write(original + separator + appended.getvalue().encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            if path.read_bytes() != original:
                raise ValueError(
                    "Sender decisions changed during discovery; retry the scan"
                )
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    return len(new)


def audit(
    path: Path,
    event: str,
    message: dict[str, str],
    detail: str = "",
) -> None:
    """Append and flush an audit event for mailbox operations."""
    new = not path.exists() or path.stat().st_size == 0

    with path.open(
        "a",
        encoding="utf-8",
        newline="",
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(LOG_FIELDS),
        )

        if new:
            writer.writeheader()

        writer.writerow(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": event,
                "id": message["id"],
                "sender": message.get("sender", ""),
                "labels": message.get("labels", ""),
                "detail": detail,
            }
        )

        stream.flush()
        os.fsync(stream.fileno())
