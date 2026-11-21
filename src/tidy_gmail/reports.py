"""Generate local inventory and candidate reports."""

from collections import Counter
from pathlib import Path

from . import scan_state, storage
from .classify import select_candidates
from .inventory import read_inventory
from .rules import (
    SenderDecisions,
    Settings,
    protected_sender_reasons,
    protection_reason,
    sender_approval,
)


def report(
    root: Path,
    settings: Settings,
    protected: set[str],
    decisions: dict[str, str],
) -> None:
    """Print and save sender counts and cleanup statistics."""
    coverage = scan_state.coverage(root, settings)
    print(f"Scan coverage: {coverage}")
    rows = read_inventory(root)
    reasons = protected_sender_reasons(root / "data")
    permanent = (
        decisions.always_delete if isinstance(decisions, SenderDecisions) else {}
    )
    conflicts = [
        {
            "email": address,
            "reason": permanent[address],
            "conflict": sender_approval(address, decisions),
        }
        for address in permanent
        if sender_approval(address, decisions).startswith("conflict:")
    ]
    storage.write_csv(
        root / "output/sender_conflicts.csv", ("email", "reason", "conflict"), conflicts
    )
    print(
        f"Sender approval conflicts: {len(conflicts)} | {root / 'output/sender_conflicts.csv'}"
    )
    # WHY: Reporting uses the same address normalization as eligibility checks.
    rows = [row | {"sender": row["sender"].strip().casefold()} for row in rows]

    protections = [
        row
        | {
            "protection_reason": protection_reason(row)
            or (
                f"sender_protected: {reasons.get(row['sender'], '')}".rstrip(": ")
                if row["sender"] in protected
                else ""
            )
        }
        for row in rows
    ]
    protections = [row for row in protections if row["protection_reason"]]
    storage.write_csv(
        root / "output" / "protected_messages.csv",
        (*storage.INVENTORY_FIELDS, "protection_reason"),
        protections,
    )
    receipt_counts = Counter(
        row["sender"]
        for row in protections
        if row["protection_reason"] == "receipt_protected"
    )
    selected = select_candidates(root, settings, protected, decisions)
    eligible_counts = Counter(row["sender"].strip().casefold() for row in selected)

    counts = Counter(row["sender"] for row in rows if row["sender"])

    summary = [
        {
            "email": address,
            "messages": str(count),
            "receipt_protected": str(receipt_counts[address]),
            "eligible_candidates": str(eligible_counts[address]),
            "decision": decisions.get(address, ""),
            "approval": sender_approval(address, decisions),
            "approval_reason": permanent.get(address, ""),
            "protected": ("yes" if address in protected else "no"),
            "protection_reason": reasons.get(address, "")
            if address in protected
            else "",
        }
        for address, count in counts.most_common()
    ]

    storage.write_csv(
        root / "output" / "sender_summary.csv",
        (
            "email",
            "messages",
            "receipt_protected",
            "eligible_candidates",
            "decision",
            "approval",
            "approval_reason",
            "protected",
            "protection_reason",
        ),
        summary,
    )

    print(f"Receipt-protected messages: {sum(receipt_counts.values())}")
    print(
        f"Protected/invalid metadata report: {root / 'output' / 'protected_messages.csv'}"
    )
    print(f"Messages scanned: {len(rows)}")
    print(f"Unique senders:   {len(counts)}")
    print(f"Approved candidates after protection: {len(selected)}")

    print("Largest senders in scan:")

    for item in summary[:15]:
        count = int(item["messages"])
        # REQ: Protection takes display precedence without changing decisions.
        if item["protected"] == "yes":
            decision = "protected"
            if item["protection_reason"]:
                decision += f": {item['protection_reason']}"
        else:
            decision = item["approval"]
            if decision in {"permanently approved", "individually approved"}:
                decision += f"; eligible: {item['eligible_candidates']}"
        if item["protected"] == "yes" and item["approval"].startswith("conflict:"):
            decision += f"; {item['approval']}"

        print(f"  {count:>6}  {item['email']} [{decision}]")

    storage.write_csv(
        root / "output" / "report_status.csv",
        ("scan_coverage",),
        [{"scan_coverage": coverage}],
    )
    print(f"Full report: {root / 'output' / 'sender_summary.csv'}")


def candidates(
    root: Path,
    settings: Settings,
    protected: set[str],
    decisions: dict[str, str],
) -> list[dict[str, str]]:
    """Generate a reviewable candidate report."""
    coverage = scan_state.coverage(root, settings)
    print(f"Scan coverage: {coverage}")
    rows = select_candidates(
        root,
        settings,
        protected,
        decisions,
    )

    path = root / "output" / "candidates.csv"

    storage.write_csv(
        path,
        storage.INVENTORY_FIELDS,
        rows,
    )

    storage.write_csv(
        root / "output" / "candidates_status.csv",
        ("scan_coverage",),
        [{"scan_coverage": coverage}],
    )
    print(f"Candidates: {len(rows)} | {path}")

    print(
        "This report is not a deletion instruction. "
        "Gmail will be rechecked before Trash."
    )

    return rows
