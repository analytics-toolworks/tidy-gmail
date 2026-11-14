"""Offline safety and rule tests; never contact Gmail."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tidy_gmail.rules import (
    eligible,
    gmail_query,
    load_settings,
    sender_rules,
)
from tidy_gmail.storage import STARTER_FILES


def setup(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    data.mkdir()

    for name, content in STARTER_FILES.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    return data


def message(**changes: str) -> dict[str, str]:
    default = {
        "id": "A1",
        "thread_id": "T1",
        "sender": "offers@example.org",
        "subject": "A sale for you",
        "internal_ms": str(
            int((datetime.now(UTC) - timedelta(days=1000)).timestamp() * 1000)
        ),
        "labels": "CATEGORY_PROMOTIONS|INBOX",
        "unsubscribe": "1",
    }
    return default | changes


def test_approved_sender_is_required(tmp_path: Path):
    data = setup(tmp_path)
    settings = load_settings(data / "config.toml")

    assert not eligible(message(), settings, set(), {})

    assert eligible(
        message(),
        settings,
        set(),
        {"offers@example.org": "trash"},
    )


@pytest.mark.parametrize(
    "change",
    [
        {"subject": "Your donation receipt"},
        {"subject": "Membership renewal"},
        {"unsubscribe": "0"},
        {"labels": "CATEGORY_PROMOTIONS|INBOX|STARRED"},
        {"labels": "CATEGORY_PROMOTIONS|INBOX|IMPORTANT"},
        {"labels": "CATEGORY_PROMOTIONS|SENT|INBOX"},
        {"labels": "CATEGORY_PROMOTIONS|TRASH"},
        {"labels": "CATEGORY_PERSONAL|INBOX"},
        {"internal_ms": str(int(datetime.now(UTC).timestamp() * 1000))},
    ],
)
def test_protected_message_never_selected(
    tmp_path: Path,
    change: dict[str, str],
):
    settings = load_settings(setup(tmp_path) / "config.toml")

    assert not eligible(
        message(**change),
        settings,
        set(),
        {"offers@example.org": "trash"},
    )


def test_protected_sender_overrides_trash(tmp_path: Path):
    settings = load_settings(setup(tmp_path) / "config.toml")

    assert not eligible(
        message(),
        settings,
        {"offers@example.org"},
        {"offers@example.org": "trash"},
    )


def test_sender_file_names_and_decisions(tmp_path: Path):
    data = setup(tmp_path)

    (data / "senders_protected.csv").write_text(
        "email,reason\nfriend@example.org,old friend\n",
        encoding="utf-8",
    )

    (data / "sender_decisions.csv").write_text(
        "email,decision,notes\noffers@example.org,trash,advertising\n",
        encoding="utf-8",
    )

    protected, decisions = sender_rules(data)

    assert protected == {"friend@example.org"}
    assert decisions == {"offers@example.org": "trash"}


def test_gmail_query_rechecks_attachment_and_inbox(
    tmp_path: Path,
):
    settings = load_settings(setup(tmp_path) / "config.toml")

    query = gmail_query(settings)

    assert "in:inbox" in query
    assert "-has:attachment" in query
    assert "category:promotions" in query
