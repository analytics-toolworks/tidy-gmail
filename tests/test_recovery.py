"""Exercise recovery boundaries without a real Gmail account."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tidy_gmail import cli, storage
from tidy_gmail.rules import eligible, load_settings


@pytest.fixture
def workspace(tmp_path):
    storage.init(tmp_path, confirm=True)
    row = {
        "id": "A1",
        "thread_id": "T1",
        "sender": "offers@example.org",
        "subject": "Sale",
        "labels": "INBOX|CATEGORY_PROMOTIONS",
        "unsubscribe": "1",
        "internal_ms": str(
            int((datetime.now(UTC) - timedelta(days=1000)).timestamp() * 1000)
        ),
    }
    storage.write_csv(
        tmp_path / "output/inventory.csv", storage.INVENTORY_FIELDS, [row]
    )
    settings = replace(load_settings(tmp_path / "data/config.toml"), dry_run=False)
    return tmp_path, row, settings


@pytest.mark.parametrize("failure", ["request", "response", "completion"])
def test_trash_audit_boundaries(workspace, monkeypatch, failure):
    root, row, settings = workspace
    calls = []
    monkeypatch.setattr(cli.gmail, "connect", lambda _: object())
    monkeypatch.setattr(cli.gmail, "list_ids", lambda *a: iter(["A1"]))
    monkeypatch.setattr(cli.gmail, "metadata", lambda *a: row.copy())
    monkeypatch.setattr("builtins.input", lambda _: "TRASH 1")
    audit = storage.audit

    def log(path, event, message, detail=""):
        if (failure == "request" and event == "trash_requested") or (
            failure == "completion" and event == "trashed"
        ):
            raise OSError("disk unavailable")
        audit(path, event, message, detail)

    def trash(*args):
        calls.append("trash")
        if failure == "response":
            raise OSError("response lost after mutation")

    monkeypatch.setattr(storage, "audit", log)
    monkeypatch.setattr(cli.gmail, "trash", trash)
    with pytest.raises(OSError):
        cli.trash(
            root, settings, set(), {row["sender"]: "trash"}, execute=True, limit=1
        )
    if failure == "request":
        assert calls == []
        assert cli.restorable(root) == []
    else:
        assert calls == ["trash"]
        assert cli.restorable(root)[0]["id"] == "A1"


def test_restore_resumes_after_untrash(workspace, monkeypatch):
    root, row, _ = workspace
    storage.audit(root / "output/cleanup_log.csv", "trash_requested", row)
    current = row | {"labels": "TRASH|CATEGORY_PROMOTIONS"}
    calls = []
    monkeypatch.setattr(cli.gmail, "connect", lambda _: object())
    monkeypatch.setattr(cli.gmail, "metadata", lambda *a: current.copy())
    monkeypatch.setattr("builtins.input", lambda _: "RESTORE 1")

    def untrash(*args):
        calls.append("untrash")
        current["labels"] = "CATEGORY_PROMOTIONS"

    def fail_inbox(*args):
        raise OSError("connection interrupted")

    monkeypatch.setattr(cli.gmail, "untrash", untrash)
    monkeypatch.setattr(cli.gmail, "add_inbox", fail_inbox)
    with pytest.raises(OSError):
        cli.restore(root, execute=True, limit=1)

    def add_inbox(*args):
        calls.append("inbox")
        current["labels"] += "|INBOX"

    monkeypatch.setattr(cli.gmail, "add_inbox", add_inbox)
    cli.restore(root, execute=True, limit=1)
    assert calls == ["untrash", "inbox"]
    assert cli.restorable(root) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"protected_labels": ("CATEGORY_PROMOTIONS",)},
        {"own_addresses": ("offers@example.org",)},
    ],
)
def test_added_protections_override_approval(workspace, changes):
    _, row, settings = workspace
    assert not eligible(
        row, replace(settings, **changes), set(), {row["sender"]: "trash"}
    )


def test_workspace_and_zero_limit(workspace):
    root, _, _ = workspace
    assert cli.main(["--workspace", str(root), "doctor"]) == 0
    assert cli.main(["--workspace", str(root), "trash", "--limit", "0"]) == 1
