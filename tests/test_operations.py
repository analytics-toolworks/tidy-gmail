"""Offline mock tests of moving to Trash and restoring."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from tidy_gmail import cli, storage
from tidy_gmail.rules import load_settings, sender_rules


def test_trash_requires_confirmation_and_restores(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "Repos" / "tidy-gmail"
    storage.init(root, confirm=True)

    config = root / "data" / "config.toml"
    config.write_text(
        config.read_text().replace(
            "dry_run = true",
            "dry_run = false",
        )
    )

    (root / "data" / "sender_decisions.csv").write_text(
        "email,decision,notes\noffers@example.org,trash,reviewed\n",
        encoding="utf-8",
    )

    row = {
        "id": "A1",
        "thread_id": "T1",
        "sender": "offers@example.org",
        "subject": "Sale",
        "internal_ms": str(
            int((datetime.now(UTC) - timedelta(days=1000)).timestamp() * 1000)
        ),
        "labels": "CATEGORY_PROMOTIONS|INBOX",
        "unsubscribe": "1",
    }

    storage.write_csv(
        root / "output" / "inventory.csv",
        storage.INVENTORY_FIELDS,
        [row],
    )

    settings = load_settings(config)
    protected, decisions = sender_rules(root / "data")

    api = object()
    mail_state = [row.copy()]
    calls = []

    monkeypatch.setattr(
        cli.gmail,
        "connect",
        lambda _: api,
    )

    monkeypatch.setattr(
        cli.gmail,
        "list_ids",
        lambda *_: iter(["A1"]),
    )

    monkeypatch.setattr(
        cli.gmail,
        "metadata",
        lambda _, __: mail_state[0].copy(),
    )

    def fake_trash(_, message_id):
        calls.append(("trash", message_id))
        mail_state[0]["labels"] = "CATEGORY_PROMOTIONS|TRASH"

    def fake_untrash(_, message_id):
        calls.append(("untrash", message_id))
        mail_state[0]["labels"] = "CATEGORY_PROMOTIONS|INBOX"

    monkeypatch.setattr(
        cli.gmail,
        "trash",
        fake_trash,
    )

    monkeypatch.setattr(
        cli.gmail,
        "untrash",
        fake_untrash,
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda _: "TRASH 1",
    )

    cli.trash(
        root,
        settings,
        protected,
        decisions,
        execute=True,
        limit=1,
    )

    assert calls == [("trash", "A1")]
    assert cli.restorable(root)[0]["id"] == "A1"

    monkeypatch.setattr(
        "builtins.input",
        lambda _: "RESTORE 1",
    )

    cli.restore(
        root,
        execute=True,
        limit=1,
    )

    assert calls == [
        ("trash", "A1"),
        ("untrash", "A1"),
    ]

    assert cli.restorable(root) == []
