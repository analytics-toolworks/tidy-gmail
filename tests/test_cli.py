"""Test local configuration and CLI without connecting to Gmail."""

import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tidy_gmail import cli, storage


def test_init_does_not_overwrite(tmp_path: Path):
    root = tmp_path / "Repos" / "tidy-gmail"

    storage.init(root, confirm=True)

    path = root / "data" / "sender_decisions.csv"
    path.write_text(
        "email,decision,notes\noffers@example.org,trash,reviewed\n",
        encoding="utf-8",
    )

    storage.init(root, confirm=True)

    assert "reviewed" in path.read_text(encoding="utf-8")
    assert (root / "data" / "senders_protected.csv").exists()


def test_report_and_candidates_are_read_only(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "Repos" / "tidy-gmail"
    storage.init(root, confirm=True)

    monkeypatch.setattr(
        cli.storage,
        "workspace",
        lambda: root,
    )

    data = [
        {
            "id": "A1",
            "thread_id": "T1",
            "sender": "offers@example.org",
            "subject": "Sale",
            "internal_ms": str(
                int((datetime.now(UTC) - timedelta(days=900)).timestamp() * 1000)
            ),
            "labels": "CATEGORY_PROMOTIONS|INBOX",
            "unsubscribe": "1",
        },
    ]

    storage.write_csv(
        root / "output" / "inventory.csv",
        storage.INVENTORY_FIELDS,
        data,
    )

    (root / "data" / "sender_decisions.csv").write_text(
        "email,decision,notes\noffers@example.org,trash,reviewed\n",
        encoding="utf-8",
    )

    assert cli.main(["doctor"]) == 0
    assert cli.main(["report"]) == 0
    assert cli.main(["candidates"]) == 0

    with (root / "output" / "candidates.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        row = next(csv.DictReader(stream), None)
        assert row is not None
        assert row["id"] == "A1"

    assert cli.main(["trash", "--limit", "1"]) == 0

    assert not (root / "output" / "cleanup_log.csv").exists()
