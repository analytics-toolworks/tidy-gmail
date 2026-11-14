"""Recover Gmail messages using durable audit events."""

from __future__ import annotations

from pathlib import Path

from . import gmail_client as gmail
from . import storage
from .cleanup import confirm


def restorable(root: Path) -> list[dict[str, str]]:
    """Find logged Trash requests not subsequently marked restored."""
    log = root / "output" / "cleanup_log.csv"

    if not log.exists():
        return []

    events = storage.read_csv(
        log,
        storage.LOG_FIELDS,
    )

    last: dict[str, str] = {}
    original: dict[str, dict[str, str]] = {}

    for event in events:
        message_id = event["id"]

        if event["event"] == "trash_requested":
            original[message_id] = event

        last[message_id] = event["event"]
        if message_id in original:
            original[message_id]["recovery_event"] = event["event"]

    return [
        original[message_id]
        for message_id in original
        if last[message_id] != "restored"
    ]


def restore(
    root: Path,
    *,
    execute: bool,
    limit: int,
) -> None:
    """Restore logged messages that still exist in Gmail Trash."""
    if limit < 1:
        raise ValueError("--limit must be positive")

    recorded = restorable(root)[:limit]

    print(f"Previously requested Trash messages available to check: {len(recorded)}")

    if not recorded or not execute:
        print("DRY RUN. Pass --execute to check Gmail and confirm restoration.")
        return

    api = gmail.connect(root)
    available: list[dict[str, str]] = []

    for row in recorded:
        try:
            current = gmail.metadata(
                api,
                row["id"],
            )

        except Exception as exc:
            if (
                getattr(
                    getattr(exc, "resp", None),
                    "status",
                    None,
                )
                == 404
            ):
                print(f"No longer available: {row['id']}")
                continue

            raise

        if "TRASH" in current["labels"].split("|") or row.get("recovery_event") in {
            "restore_requested",
            "restore_failed",
        }:
            available.append(row)

    print(f"Messages eligible for recovery: {len(available)}")

    if not available or not confirm(
        "RESTORE",
        len(available),
    ):
        print("Cancelled.")
        return

    log = root / "output" / "cleanup_log.csv"
    count = 0

    for row in available:
        storage.audit(
            log,
            "restore_requested",
            row,
        )

        try:
            current = gmail.metadata(api, row["id"])
            if "TRASH" in current["labels"].split("|"):
                gmail.untrash(api, row["id"])

            # Preserve original Inbox membership.
            if "INBOX" in row["labels"].split("|"):
                now = gmail.metadata(
                    api,
                    row["id"],
                )

                if "INBOX" not in now["labels"].split("|"):
                    gmail.add_inbox(
                        api,
                        row["id"],
                    )

        except Exception as exc:
            storage.audit(
                log,
                "restore_failed",
                row,
                type(exc).__name__,
            )
            raise

        storage.audit(
            log,
            "restored",
            row,
        )

        count += 1

    print(f"Restored {count} messages. Audit: {log}")
