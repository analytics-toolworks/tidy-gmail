"""Validate Gmail adapter requests using simulated responses."""

from unittest.mock import MagicMock

from tidy_gmail import gmail_client as gmail
from tidy_gmail import inventory, storage
from tidy_gmail.rules import load_settings


def test_search_pagination_deduplicates_and_limits():
    api = MagicMock()
    endpoint = api.users.return_value.messages.return_value
    endpoint.list.return_value.execute.side_effect = [
        {"messages": [{"id": "A"}], "nextPageToken": "next"},
        {"messages": [{"id": "A"}, {"id": "B"}, {"id": "C"}]},
    ]
    assert list(gmail.list_ids(api, "in:inbox", limit=2)) == ["A", "B"]
    assert endpoint.list.call_args.kwargs["pageToken"] == "next"
    assert endpoint.list.call_args.kwargs["includeSpamTrash"] is False


def test_metadata_does_not_request_bodies():
    api = MagicMock()
    endpoint = api.users.return_value.messages.return_value
    endpoint.get.return_value.execute.return_value = {
        "id": "A",
        "threadId": "T",
        "internalDate": "1000",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": "Offers <OFFERS@example.org>"},
                {"name": "Subject", "value": "Sale"},
                {"name": "List-Unsubscribe", "value": "<mailto:leave@example.org>"},
            ]
        },
    }
    row = gmail.metadata(api, "A")
    assert row["sender"] == "offers@example.org"
    assert row["unsubscribe"] == "1"
    assert endpoint.get.call_args.kwargs["format"] == "metadata"


def test_mutations_target_messages_not_threads():
    api = MagicMock()
    endpoint = api.users.return_value.messages.return_value
    gmail.trash(api, "A")
    gmail.untrash(api, "A")
    gmail.add_inbox(api, "A")
    endpoint.trash.assert_called_once_with(userId="me", id="A")
    endpoint.untrash.assert_called_once_with(userId="me", id="A")
    endpoint.modify.assert_called_once_with(
        userId="me", id="A", body={"addLabelIds": ["INBOX"]}
    )
    api.users.return_value.threads.assert_not_called()
    endpoint.delete.assert_not_called()


def test_scan_preserves_existing_sender_decisions(tmp_path, monkeypatch):
    storage.init(tmp_path, confirm=True)
    path = tmp_path / "data/sender_decisions.csv"
    path.write_text(
        "email,decision,notes\nold@example.org,keep,personal\n", encoding="utf-8"
    )
    monkeypatch.setattr(gmail, "connect", lambda _: object())
    monkeypatch.setattr(gmail, "list_page", lambda *a: (["A", "B"], None))
    monkeypatch.setattr(gmail, "scan_account", lambda _: "synthetic")

    def metadata(api, message_id):
        return {
            name: (
                message_id
                if name == "id"
                else "new@example.org"
                if name == "sender"
                else ""
            )
            for name in storage.INVENTORY_FIELDS
        }

    monkeypatch.setattr(gmail, "metadata", metadata)
    inventory.scan(tmp_path, load_settings(tmp_path / "data/config.toml"), limit=2)
    rows = storage.read_csv(path, ("email", "decision", "notes"))
    assert rows == [
        {"email": "old@example.org", "decision": "keep", "notes": "personal"},
        {"email": "new@example.org", "decision": "", "notes": ""},
    ]
