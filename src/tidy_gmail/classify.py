"""Classify inventory using current protection rules."""

from pathlib import Path

from .inventory import read_inventory
from .rules import Settings, eligible


def select_candidates(
    root: Path,
    settings: Settings,
    protected: set[str],
    decisions: dict[str, str],
) -> list[dict[str, str]]:
    """Select messages using current user-maintained rules."""
    rows = read_inventory(root)

    ids = [row["id"] for row in rows]

    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate Gmail message IDs in inventory; scan again")

    return [
        row
        for row in rows
        if eligible(
            row,
            settings,
            protected,
            decisions,
        )
    ]
