"""Permanent sender approvals never bypass message or sender protections."""

import csv
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from tidy_gmail import cleanup, cli, gmail_client, inventory, storage
from tidy_gmail.rules import eligible, sender_approval, sender_rules


@pytest.fixture
def setup(tmp_path):
    storage.init(tmp_path, confirm=True)
    (tmp_path / "data/senders_always_delete.csv").write_text(
        "email,reason\n Offers@Example.org ,advertising\n", encoding="utf-8"
    )
    row = {
        "id": "A1",
        "thread_id": "T1",
        "sender": "offers@example.org",
        "subject": "Summer sale",
        "internal_ms": str(
            int((datetime.now(UTC) - timedelta(days=1000)).timestamp() * 1000)
        ),
        "labels": "INBOX|CATEGORY_PROMOTIONS",
        "unsubscribe": "1",
    }
    storage.write_csv(
        tmp_path / "output/inventory.csv", storage.INVENTORY_FIELDS, [row]
    )
    return tmp_path, row


def test_large_list_and_selected_workspace(setup, monkeypatch, tmp_path):
    root, row = setup
    path = root / "data/senders_always_delete.csv"
    path.write_text(
        "email,reason\n"
        + "".join(f"sender{i}@example.org,approved\n" for i in range(20000))
        + "offers@example.org,advertising\n",
        encoding="utf-8",
    )
    private = {p: p.read_bytes() for p in (root / "data").iterdir()}
    monkeypatch.setattr(storage, "workspace", lambda: tmp_path / "wrong-workspace")
    assert cli.main(["--workspace", str(root), "candidates"]) == 0
    assert storage.read_csv(
        root / "output/candidates.csv", storage.INVENTORY_FIELDS
    ) == [row]
    _, decisions = sender_rules(root / "data")
    assert len(decisions.always_delete) == 20001
    assert decisions.get(row["sender"]) is None
    assert all(p.read_bytes() == content for p, content in private.items())


def test_absent_file_preserves_old_behavior(setup):
    root, row = setup
    (root / "data/senders_always_delete.csv").unlink()
    settings, protected, decisions = cli.prepare(root)
    assert not eligible(row, settings, protected, decisions)
    decisions[row["sender"]] = "trash"
    assert eligible(row, settings, protected, decisions)


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "email,notes\nx@example.org,why\n",
        "email,reason\nName <x@example.org>,why\n",
        "email,reason\nx@example.org,one\nX@example.org,two\n",
        "email,reason\n@,bad\n",
        "email,reason\nx@example.org\n",
    ],
)
def test_malformed_lists_fail_closed(setup, contents):
    root, _ = setup
    (root / "data/senders_always_delete.csv").write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError):
        cli.prepare(root)


@pytest.mark.parametrize("decision", ["keep", "review"])
def test_conflicts_block_and_report(setup, capsys, decision):
    root, row = setup
    (root / "data/sender_decisions.csv").write_text(
        f"email,decision,notes\noffers@example.org,{decision},preserve\n",
        encoding="utf-8",
    )
    settings, protected, decisions = cli.prepare(root)
    assert not eligible(row, settings, protected, decisions)
    assert cli.main(["--workspace", str(root), "report"]) == 0
    assert f"conflict: permanent approval with {decision}" in capsys.readouterr().out
    conflicts = storage.read_csv(
        root / "output/sender_conflicts.csv", ("email", "reason", "conflict")
    )
    assert conflicts[0]["email"] == row["sender"]


@pytest.mark.parametrize(
    "change",
    [
        {"subject": "Receipt"},
        {"subject": "Order confirmation"},
        {"subject": "Donation acknowledgement"},
        {"labels": "INBOX|CATEGORY_PROMOTIONS|STARRED"},
        {"labels": "INBOX|CATEGORY_PROMOTIONS|IMPORTANT"},
        {"labels": "INBOX|CATEGORY_PROMOTIONS|SENT"},
        {"labels": "CATEGORY_PROMOTIONS"},
        {"labels": "INBOX|CATEGORY_PERSONAL"},
        {"labels": "INBOX|CATEGORY_PROMOTIONS|TRASH"},
        {"unsubscribe": "0"},
        {"subject": ""},
        {"subject": None},
        {"internal_ms": "bad"},
        {"internal_ms": str(int(datetime.now(UTC).timestamp() * 1000))},
    ],
)
def test_message_safeguards_win(setup, change):
    root, row = setup
    settings, protected, decisions = cli.prepare(root)
    assert eligible(row, settings, protected, decisions)
    assert not eligible(row | change, settings, protected, decisions)


def test_sender_and_label_protections_win(setup):
    root, row = setup
    settings, protected, decisions = cli.prepare(root)
    assert not eligible(row, settings, {row["sender"]}, decisions)
    assert not eligible(
        row,
        replace(settings, protected_labels=("CATEGORY_PROMOTIONS",)),
        protected,
        decisions,
    )
    assert not eligible(
        row, replace(settings, own_addresses=(row["sender"],)), protected, decisions
    )


@pytest.mark.parametrize(
    "final",
    [
        "ok",
        "receipt",
        "missing",
        "malformed",
        "attachment",
        "keep",
        "protected",
        "dry_run",
        "recent",
        "missing_date",
        "invalid_date",
    ],
)
def test_live_execution_rechecks_all_protections(setup, monkeypatch, final):
    root, row = setup
    settings, protected, decisions = cli.prepare(root)
    settings = replace(settings, dry_run=final == "dry_run")
    connect = MagicMock(return_value=object())
    monkeypatch.setattr(gmail_client, "connect", connect)
    queries = 0

    def ids(*args):
        nonlocal queries
        queries += 1
        return iter([] if final == "attachment" and queries > 1 else ["A1"])

    monkeypatch.setattr(gmail_client, "list_ids", ids)
    reads = 0

    def metadata(*args):
        nonlocal reads
        reads += 1
        if reads > 1:
            if final == "recent":
                return row | {
                    "internal_ms": str(int(datetime.now(UTC).timestamp() * 1000))
                }
            if final == "missing_date":
                return row | {"internal_ms": ""}
            if final == "invalid_date":
                return row | {"internal_ms": "not-a-date"}
            if final == "receipt":
                return row | {"subject": "Order confirmation"}
            if final == "missing":
                return row | {"subject": ""}
            if final == "malformed":
                return None
        return row.copy()

    monkeypatch.setattr(gmail_client, "metadata", metadata)

    def confirm(*args):
        if final == "keep":
            decisions[row["sender"]] = "keep"
        if final == "protected":
            protected.add(row["sender"])
        return True

    monkeypatch.setattr(cleanup, "confirm", confirm)
    mutation = MagicMock()
    monkeypatch.setattr(gmail_client, "trash", mutation)
    cleanup.trash(root, settings, protected, decisions, execute=True, limit=1)
    if final == "ok":
        mutation.assert_called_once()
        assert queries == 2 and reads == 2
    else:
        mutation.assert_not_called()
    if final == "dry_run":
        connect.assert_not_called()


def test_scan_never_populates_permanent_list(setup, monkeypatch):
    root, row = setup
    path = root / "data/senders_always_delete.csv"
    original = path.read_bytes()
    monkeypatch.setattr(gmail_client, "connect", lambda _: object())
    monkeypatch.setattr(gmail_client, "list_page", lambda *args: (["A1"], None))
    monkeypatch.setattr(
        gmail_client, "metadata", lambda *args: row | {"sender": "new@example.org"}
    )
    monkeypatch.setattr(gmail_client, "scan_account", lambda _: "synthetic")
    settings, _, _ = cli.prepare(root)
    inventory.scan(root, settings, limit=1, restart=True)
    assert path.read_bytes() == original
    storage.init(root, confirm=True)
    assert path.read_bytes() == original


def test_report_distinguishes_approvals(setup, capsys):
    root, row = setup
    assert cli.main(["--workspace", str(root), "report"]) == 0
    assert "[permanently approved; eligible: 1]" in capsys.readouterr().out
    with (root / "output/sender_summary.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        summary = next(csv.DictReader(stream))
    assert summary["decision"] == ""
    assert summary["approval_reason"] == "advertising"
    assert sender_approval(row["sender"], {}) == "undecided"


@pytest.mark.parametrize("delta_ms, expected", [(-1, True), (0, False), (1, False)])
def test_permanent_approval_obeys_age_boundary(setup, delta_ms, expected):
    root, row = setup
    settings, protected, decisions = cli.prepare(root)
    now = datetime(2026, 11, 14, tzinfo=UTC)
    cutoff = int((now - timedelta(days=settings.minimum_age_days)).timestamp() * 1000)
    assert (
        eligible(
            row | {"internal_ms": str(cutoff + delta_ms)},
            settings,
            protected,
            decisions,
            now=now,
        )
        is expected
    )


def test_configured_dry_run_blocks_restore(setup):
    root, row = setup
    storage.audit(root / "output/cleanup_log.csv", "trash_requested", row)
    # The autouse fixture raises if the command tries to authorize Gmail.
    assert cli.main(["--workspace", str(root), "restore", "--execute"]) == 0
