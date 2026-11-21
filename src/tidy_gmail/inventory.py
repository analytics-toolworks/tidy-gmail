"""Collect Gmail metadata and discover senders."""

from pathlib import Path
from typing import Any

from . import gmail_client as gmail
from . import scan_state, storage
from .rules import Settings


def read_inventory(root: Path) -> list[dict[str, str]]:
    """Read committed accumulated metadata, including partial scans."""
    if scan_state.checkpoint_path(root).exists():
        return scan_state.read_rows(root)
    path = root / "output" / "inventory.csv"

    if not path.exists():
        raise FileNotFoundError(f"Run tidy-gmail scan first: {path}")

    return storage.read_csv(
        path,
        storage.INVENTORY_FIELDS,
    )


def scan(
    root: Path,
    settings: Settings,
    *,
    limit: int,
    restart: bool = False,
) -> None:
    """Resume up to limit additional unique messages, committing each result."""
    if limit < 1:
        raise ValueError("--limit must be positive")
    with scan_state.scan_lock(root):
        state = scan_state.ScanState(root, settings, restart=restart)
        try:
            if state.state["complete"] and not restart:
                state.export()
                print(
                    "Status: Complete - eligible query exhausted; use --restart for a fresh scan"
                )
                return
            api = gmail.connect(root)
            state.bind(gmail.scan_account(api), settings, restart=restart)
            _scan_pages(api, root, state, limit)
        finally:
            state.close()


def _scan_pages(api: Any, root: Path, state: scan_state.ScanState, limit: int) -> None:
    """Process durable pending pages without holding the full inventory in RAM."""
    before, _ = state.counts()
    processed = 0
    print(f"Gmail query: {state.state['query']}")
    print(f"Previously processed: {before}; this run: up to {limit} new unique IDs")
    try:
        while processed < limit and not state.state["complete"]:
            if state.state["pending"] is None:
                token = state.state["token"]
                try:
                    ids, next_token = gmail.list_page(api, state.state["query"], token)
                except Exception as exc:
                    status = getattr(getattr(exc, "resp", None), "status", None)
                    if token and status in {400, 404, 410}:
                        raise ValueError(
                            "Gmail rejected a pagination token. Progress is preserved; use scan --restart to archive this scan and begin again."
                        ) from exc
                    raise
                state.load_page(ids, next_token)
                if state.state["pending"] is None:
                    continue
            message_id = state.state["pending"][state.state["offset"]]
            if state.known(message_id):
                state.record(message_id, None)
                continue
            try:
                row = gmail.read_with_retry(
                    lambda message_id=message_id: gmail.metadata(api, message_id)
                )
            except Exception as exc:
                if getattr(getattr(exc, "resp", None), "status", None) == 404:
                    state.record(message_id, None, skipped="not_found")
                    processed += 1
                    continue
                raise
            if (
                not isinstance(row, dict)
                or row.get("id") != message_id
                or any(
                    not isinstance(row.get(name), str)
                    for name in storage.INVENTORY_FIELDS
                )
            ):
                raise ValueError(
                    "Malformed Gmail metadata; position preserved for retry"
                )
            state.record(message_id, row)
            processed += 1
            if processed % 250 == 0:
                print(f"Inspected {processed} new messages; checkpoint saved")
    except KeyboardInterrupt:
        state.fail("Interrupted; resume with scan --limit N")
        raise
    except Exception as exc:
        # WHY: Record a safe error category without persisting tokens or response bodies.
        state.fail(f"Read failed: {type(exc).__name__}; progress preserved")
        if isinstance(exc, ValueError):
            raise
        raise ValueError(
            f"Scan stopped ({type(exc).__name__}); saved progress will resume on the next scan"
        ) from exc
    finally:
        # SQLite is authoritative if interruption or disk errors prevent this export.
        added = state.export()
        total, skipped = state.counts()
        print(f"Processed this run: {total - before}; total unique processed: {total}")
        print(
            f"Metadata collected: {total - skipped}; unavailable: {skipped}; new senders: {added}"
        )
        print(f"Checkpoint saved: {scan_state.checkpoint_path(root)}")
        status = (
            "Complete - eligible query exhausted"
            if state.state["complete"]
            else "Incomplete - resumable"
        )
        print(f"Status: {status}")
        print("No Gmail messages modified")
