"""Execute explicitly confirmed Gmail cleanup operations."""

from pathlib import Path
from typing import Any

from . import gmail_client as gmail
from . import storage
from .classify import select_candidates
from .rules import Settings, eligible, gmail_query, protection_reason, sender_approval


def confirm(action: str, count: int) -> bool:
    """Require an explicit confirmation for a modifying batch."""
    required = f"{action} {count}"

    print(f"Type {required!r} to authorize this batch. It may take a while.")

    return input("> ").strip() == required


def trash(
    root: Path,
    settings: Settings,
    protected: set[str],
    decisions: dict[str, str],
    *,
    execute: bool,
    limit: int,
) -> None:
    """Revalidate approved messages before moving them to Trash."""
    if not 1 <= limit <= settings.batch_size:
        raise ValueError(
            f"--limit must be 1..{settings.batch_size} (config batch_size)"
        )

    all_candidates = select_candidates(
        root,
        settings,
        protected,
        decisions,
    )

    print(f"Saved candidates: {len(all_candidates)}. Trash batch limit: {limit}.")

    if not all_candidates:
        return

    if settings.dry_run or not execute:
        print("DRY RUN. For execution, set cleanup.dry_run=false and pass --execute.")
        return

    api = gmail.connect(root)

    # Recheck Gmail's current category, age, Inbox,
    # starred, important, and attachment search conditions.
    current_ids = set(
        gmail.list_ids(
            api,
            gmail_query(settings),
        )
    )

    approved: list[dict[str, str]] = []

    for stored in all_candidates:
        if stored["id"] not in current_ids:
            continue

        current = checked_metadata(api, stored, settings, protected, decisions)
        if current is None:
            continue

        approved.append(current)
        if len(approved) == limit:
            break

    print(f"Still eligible after live Gmail recheck: {len(approved)}")

    if not approved or not confirm(
        "TRASH",
        len(approved),
    ):
        print("Cancelled. No messages changed.")
        return

    log = root / "output" / "cleanup_log.csv"
    count = 0

    for stored in approved:
        # WHY: Attachment and from:me protections rely on current Gmail search.
        try:
            matches = any(
                message_id == stored["id"]
                for message_id in gmail.list_ids(api, gmail_query(settings))
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Skipped {stored['id']}: search_unavailable ({type(exc).__name__})")
            continue
        if not matches:
            print(f"Skipped {stored['id']}: current Gmail protections")
            continue
        # REQ: Recheck after confirmation, immediately before each mutation.
        row = checked_metadata(api, stored, settings, protected, decisions)
        if row is None:
            continue
        # Log the intention before issuing the Gmail operation.
        storage.audit(
            log,
            "trash_requested",
            row,
        )

        try:
            gmail.trash(
                api,
                row["id"],
            )

        except Exception as exc:
            storage.audit(
                log,
                "trash_failed",
                row,
                type(exc).__name__,
            )
            raise

        storage.audit(
            log,
            "trashed",
            row,
        )

        count += 1

    print(f"Moved {count} individual messages to Gmail Trash. Audit: {log}")


def checked_metadata(
    api: Any,
    stored: dict[str, str],
    settings: Settings,
    protected: set[str],
    decisions: dict[str, str],
) -> dict[str, str] | None:
    """Skip messages whose current metadata cannot authorize cleanup safely."""
    message_id = stored["id"]
    try:
        current = gmail.metadata(api, message_id)
        reason = protection_reason(current)
        if not reason and current.get("sender", "").strip().casefold() in protected:
            reason = "sender_protected"
        if not reason:
            approval = sender_approval(current.get("sender", ""), decisions)
            if approval.startswith("conflict:"):
                reason = approval
        if not reason and (
            current.get("id") != message_id
            or current.get("sender") != stored.get("sender")
            or current.get("subject") != stored.get("subject")
        ):
            reason = "metadata_changed"
        if not reason and not eligible(current, settings, protected, decisions):
            reason = "existing_protection_or_ineligible"
    except Exception as exc:  # noqa: BLE001
        # WHY: API failures and malformed responses are never permission to delete.
        print(f"Skipped {message_id}: metadata_unavailable ({type(exc).__name__})")
        return None
    if reason:
        print(f"Skipped {message_id}: {reason}")
        return None
    return current
