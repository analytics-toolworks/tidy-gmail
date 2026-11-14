"""Protected senders override approvals independently of receipt detection."""

import csv
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from tidy_gmail import cleanup, cli, storage
from tidy_gmail.rules import eligible, protection_reason


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "selected"
    storage.init(root, confirm=True)
    (root / "data/senders_protected.csv").write_text(
        "email,reason\n BANK@example.org ,institution\nfamily@example.org,\n",
        encoding="utf-8",
    )
    (root / "data/sender_decisions.csv").write_text(
        "email,decision,notes\nbank@example.org,trash,keep this decision\nshop@example.org,trash,approved\n",
        encoding="utf-8",
    )
    row = {
        "id": "A1",
        "thread_id": "T1",
        "sender": "BANK@EXAMPLE.ORG",
        "subject": "Summer offers",
        "labels": "CATEGORY_PROMOTIONS|INBOX",
        "unsubscribe": "1",
        "internal_ms": str(
            int((datetime.now(UTC) - timedelta(days=1000)).timestamp() * 1000)
        ),
    }
    storage.write_csv(
        root / "output/inventory.csv",
        storage.INVENTORY_FIELDS,
        [
            row,
            row | {"id": "A2", "sender": "unknown@example.org"},
            row | {"id": "A3", "sender": "shop@example.org"},
            row | {"id": "A4", "sender": "family@example.org"},
        ],
    )
    return root, row


def test_selected_workspace_report_and_candidates(
    workspace, tmp_path, monkeypatch, capsys
):
    root, _row = workspace
    other = tmp_path / "default"
    storage.init(other, confirm=True)
    monkeypatch.setattr(storage, "workspace", lambda: other)
    private = {p: p.read_bytes() for p in (root / "data").iterdir()}
    assert cli.main(["--workspace", str(root), "report"]) == 0
    output = capsys.readouterr().out
    assert "bank@example.org [protected: institution]" in output
    assert "family@example.org [protected]" in output
    assert "unknown@example.org [undecided]" in output
    assert "shop@example.org [individually approved; eligible: 1]" in output
    with (root / "output/sender_summary.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        summary = {item["email"]: item for item in csv.DictReader(stream)}
    assert summary["bank@example.org"]["decision"] == "trash"
    assert summary["bank@example.org"]["protection_reason"] == "institution"
    assert summary["bank@example.org"]["eligible_candidates"] == "0"
    assert cli.main(["--workspace", str(root), "candidates"]) == 0
    candidates = storage.read_csv(
        root / "output/candidates.csv", storage.INVENTORY_FIELDS
    )
    assert [item["id"] for item in candidates] == ["A3"]
    assert all(p.read_bytes() == data for p, data in private.items())
    assert not (other / "output/sender_summary.csv").exists()
    protected_rows = storage.read_csv(
        root / "output/protected_messages.csv",
        (*storage.INVENTORY_FIELDS, "protection_reason"),
    )
    assert {item["id"] for item in protected_rows} == {"A1", "A4"}


def test_protected_nonreceipt_cannot_be_approved(workspace, monkeypatch):
    root, row = workspace
    settings, protected, decisions = cli.prepare(root)
    assert (
        protection_reason(row) == ""
    )  # No receipt or metadata safeguard masks sender protection.
    assert not eligible(row, settings, protected, decisions)
    monkeypatch.setattr(cli.gmail, "metadata", lambda *args: row.copy())
    assert (
        cleanup.checked_metadata(object(), row, settings, protected, decisions) is None
    )
    mutation = MagicMock()
    monkeypatch.setattr(cli.gmail, "trash", mutation)
    storage.write_csv(root / "output/inventory.csv", storage.INVENTORY_FIELDS, [row])
    cleanup.trash(
        root,
        replace(settings, dry_run=False),
        protected,
        decisions,
        execute=True,
        limit=1,
    )
    mutation.assert_not_called()


def test_final_check_blocks_protection_added_after_confirmation(
    workspace, monkeypatch, capsys
):
    root, row = workspace
    settings, _, decisions = cli.prepare(root)
    protected = set()
    storage.write_csv(root / "output/inventory.csv", storage.INVENTORY_FIELDS, [row])
    monkeypatch.setattr(cli.gmail, "connect", lambda _: object())
    monkeypatch.setattr(cli.gmail, "list_ids", lambda *args: iter(["A1"]))
    monkeypatch.setattr(cli.gmail, "metadata", lambda *args: row.copy())

    def confirm(*args):
        protected.add("bank@example.org")
        return True

    monkeypatch.setattr(cleanup, "confirm", confirm)
    mutation = MagicMock()
    monkeypatch.setattr(cli.gmail, "trash", mutation)
    cleanup.trash(
        root,
        replace(settings, dry_run=False),
        protected,
        decisions,
        execute=True,
        limit=1,
    )
    mutation.assert_not_called()
    assert "Skipped A1: sender_protected" in capsys.readouterr().out
    assert not (root / "output/cleanup_log.csv").exists()
