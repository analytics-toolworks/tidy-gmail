"""Private transactional checkpoints for bounded-memory Gmail scanning."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any
from uuid import uuid4

from . import storage
from .rules import Settings, gmail_query

SCHEMA_VERSION = 1


def identity(settings: Settings) -> str:
    """Identify query and protection settings, excluding execution-only options."""
    values = asdict(settings)
    for name in ("dry_run", "batch_size"):
        values.pop(name)
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def checkpoint_path(root: Path) -> Path:
    """Return the private scan database path."""
    return root / ".local" / "scan.sqlite"


@contextmanager
def scan_lock(root: Path) -> Generator[None]:
    """Prevent simultaneous scanners; SQLite releases the lock after a crash."""
    connection = sqlite3.connect(root / ".local" / "scan_lock.sqlite", timeout=0)
    try:
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise ValueError("Another scan is running for this workspace") from exc
        yield
    finally:
        connection.rollback()
        connection.close()


class ScanState:
    """Persist each successful metadata result and cursor advancement together."""

    def __init__(
        self, root: Path, settings: Settings, *, restart: bool = False
    ) -> None:
        """Validate prior state before making changes or connecting to Gmail."""
        self.root = root
        path = checkpoint_path(root)
        existed = path.exists()
        legacy = root / "output" / "inventory.csv"
        if not existed and legacy.exists() and not restart:
            raise ValueError(
                "Existing inventory has no checkpoint. Use scan --restart to archive it and start a resumable scan."
            )
        if not existed and legacy.exists():
            archive = self.archive_path(".csv")
            shutil.copy2(legacy, archive)
            print(f"Previous inventory preserved: {archive}")
        self.state: dict[str, Any] = {}
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        try:
            if not existed:
                with self.transaction():
                    self.db.execute("BEGIN IMMEDIATE")
                    self.db.execute(
                        "CREATE TABLE progress (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)"
                    )
                    self.db.execute(
                        "CREATE TABLE messages (id TEXT PRIMARY KEY, metadata TEXT, skipped TEXT NOT NULL DEFAULT '')"
                    )
                    self.db.execute("CREATE TABLE pages (token TEXT PRIMARY KEY)")
                    self.state = self.new_state(settings)
                    self.save()
            else:
                row = self.db.execute(
                    "SELECT payload FROM progress WHERE id=1"
                ).fetchone()
                if row is None:
                    raise ValueError(
                        "Scan checkpoint is incomplete or corrupt; preserve it for recovery"
                    )
                self.state = json.loads(row[0])
                if self.state.get("schema") != SCHEMA_VERSION:
                    raise ValueError(
                        "Unsupported scan checkpoint version; preserve it for recovery"
                    )
                if (
                    self.state["identity"] != identity(settings)
                    or self.state["query"] != gmail_query(settings)
                ) and not restart:
                    raise ValueError(
                        "Query or protection settings changed. Use scan --restart to archive the prior scan and start a compatible one."
                    )
                # Restart is deferred until the authenticated account has been checked.
        except BaseException:
            self.db.close()
            raise

    @staticmethod
    def new_state(settings: Settings) -> dict[str, Any]:
        """Create an incomplete traversal with a stable configuration identity."""
        return {
            "schema": SCHEMA_VERSION,
            "identity": identity(settings),
            "query": gmail_query(settings),
            "account": None,
            "token": None,
            "pending": None,
            "offset": 0,
            "next_token": None,
            "complete": False,
            "error": "",
            "started": datetime.now(UTC).isoformat(),
            "updated": "",
        }

    def archive_path(self, suffix: str) -> Path:
        """Allocate a unique private archive without overwriting previous scans."""
        directory = self.root / ".local" / "scan-archives"
        directory.mkdir(exist_ok=True)
        return directory / f"scan-{uuid4().hex}{suffix}"

    def bind(self, account: str, settings: Settings, *, restart: bool) -> None:
        """Reject another mailbox, and restart only when explicitly requested."""
        if self.state["account"] not in (None, account):
            raise ValueError(
                "Checkpoint belongs to a different Gmail account; use a separate workspace"
            )
        if restart:
            archive = self.archive_path(".sqlite")
            destination = sqlite3.connect(archive)
            try:
                self.db.backup(destination)
            finally:
                destination.close()
            print(f"Previous scan preserved: {archive}")
        with self.transaction():
            if restart:
                self.db.execute("DELETE FROM messages")
                self.db.execute("DELETE FROM pages")
                self.state = self.new_state(settings)
                print(
                    "Starting a fresh scan; the previous scan is preserved in its archive."
                )
            self.state["account"] = account
            self.state["error"] = ""
            self.save()

    @contextmanager
    def transaction(self) -> Generator[None]:
        """Roll back both SQLite and the in-memory cursor on any interruption."""
        previous = deepcopy(self.state)
        try:
            with self.db:
                yield
        except BaseException:
            self.state = previous
            raise

    def save(self) -> None:
        """Write progress inside the caller's SQLite transaction."""
        self.state["updated"] = datetime.now(UTC).isoformat()
        self.db.execute(
            "INSERT OR REPLACE INTO progress VALUES (1, ?)", (json.dumps(self.state),)
        )

    def close(self) -> None:
        """Release the checkpoint connection."""
        self.db.close()

    def known(self, message_id: str) -> bool:
        """Use the primary-key index to avoid repeated metadata requests."""
        return (
            self.db.execute(
                "SELECT 1 FROM messages WHERE id=?", (message_id,)
            ).fetchone()
            is not None
        )

    def load_page(self, ids: list[str], next_token: str | None) -> None:
        """Commit the complete pending page before processing its first message."""
        token = self.state["token"] or ""
        if next_token and (
            next_token == token
            or self.db.execute(
                "SELECT 1 FROM pages WHERE token=?", (next_token,)
            ).fetchone()
        ):
            raise ValueError(
                "Gmail returned a repeated page token; use scan --restart to recover"
            )
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO pages VALUES (?)", (token,))
            self.state.update(pending=ids, offset=0, next_token=next_token)
            self.finish_page()
            self.save()

    def finish_page(self) -> None:
        """Advance only after every ID in the persisted page has been handled."""
        pending = self.state["pending"]
        if pending is not None and self.state["offset"] >= len(pending):
            self.state.update(
                token=self.state["next_token"],
                pending=None,
                offset=0,
                complete=self.state["next_token"] is None,
            )

    def record(
        self, message_id: str, row: dict[str, str] | None, *, skipped: str = ""
    ) -> None:
        """Commit one result and its page position atomically, including deduplication."""
        with self.transaction():
            if row is not None or skipped:
                self.db.execute(
                    "INSERT OR IGNORE INTO messages VALUES (?, ?, ?)",
                    (message_id, json.dumps(row) if row is not None else None, skipped),
                )
            self.state["offset"] += 1
            self.finish_page()
            self.save()

    def fail(self, reason: str) -> None:
        """Keep an interrupted traversal explicitly incomplete."""
        with self.transaction():
            self.state["error"] = reason
            self.save()

    def counts(self) -> tuple[int, int]:
        """Return unique processed IDs and unavailable-message counts."""
        total, skipped = self.db.execute(
            "SELECT count(*), count(*) - count(metadata) FROM messages"
        ).fetchone()
        return total, skipped

    def rows(self) -> Iterator[dict[str, str]]:
        """Stream cached metadata without loading the entire mailbox into memory."""
        for (metadata,) in self.db.execute(
            "SELECT metadata FROM messages WHERE metadata IS NOT NULL ORDER BY rowid"
        ):
            yield json.loads(metadata)

    def export(self) -> int:
        """Publish accumulated metadata and append only newly discovered senders."""
        storage.write_csv(
            self.root / "output" / "inventory.csv",
            storage.INVENTORY_FIELDS,
            self.rows(),
        )
        # Sender discovery is replayable after a crash; existing decisions win.
        senders = (row["sender"] for row in self.rows() if row["sender"])
        added = storage.append_senders(
            self.root / "data" / "sender_decisions.csv", senders
        )
        storage.write_csv(
            self.root / "output" / "scan_unavailable.csv",
            ("id", "reason"),
            (
                {"id": item[0], "reason": item[1]}
                for item in self.db.execute(
                    "SELECT id, skipped FROM messages WHERE metadata IS NULL"
                )
            ),
        )
        total, skipped = self.counts()
        storage.write_csv(
            self.root / "output" / "scan_status.csv",
            ("status", "query", "processed", "unavailable", "updated"),
            [
                {
                    "status": "complete" if self.state["complete"] else "partial",
                    "query": self.state["query"],
                    "processed": str(total),
                    "unavailable": str(skipped),
                    "updated": self.state["updated"],
                }
            ],
        )
        return added


def read_checkpoint(root: Path) -> sqlite3.Connection:
    """Open an existing checkpoint read-only for reports and candidates."""
    return sqlite3.connect(
        checkpoint_path(root).resolve().as_uri() + "?mode=ro", uri=True
    )


def read_rows(root: Path) -> list[dict[str, str]]:
    """Read committed accumulated results even if a crash prevented CSV export."""
    db = read_checkpoint(root)
    try:
        return [
            json.loads(row[0])
            for row in db.execute(
                "SELECT metadata FROM messages WHERE metadata IS NOT NULL ORDER BY rowid"
            )
        ]
    finally:
        db.close()


def coverage(root: Path, settings: Settings) -> str:
    """Label report coverage without mistaking legacy or changed queries for complete scans."""
    if not checkpoint_path(root).exists():
        return "Partial / unknown: legacy inventory has no scan checkpoint"
    db = read_checkpoint(root)
    try:
        state = json.loads(
            db.execute("SELECT payload FROM progress WHERE id=1").fetchone()[0]
        )
    finally:
        db.close()
    if state["identity"] != identity(settings) or state["query"] != gmail_query(
        settings
    ):
        return "Partial: query or protection settings changed; scan --restart required"
    if state["complete"]:
        return "Complete: eligible query exhausted (not a fixed mailbox snapshot)"
    return "Partial: scan incomplete; resumable" + (
        f" ({state['error']})" if state["error"] else ""
    )
