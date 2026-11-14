"""Receipt protection is independent of sender approval and live state."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from tidy_gmail import cleanup, gmail_client, reports, storage
from tidy_gmail.rules import eligible, is_receipt, load_settings, protection_reason


@pytest.fixture
def setup(tmp_path):
    storage.init(tmp_path, confirm=True)
    settings = replace(
        load_settings(tmp_path / "data/config.toml"),
        dry_run=False,
        categories=("CATEGORY_PROMOTIONS", "CATEGORY_UPDATES"),
    )
    row = {
        "id": "A1",
        "thread_id": "T1",
        "sender": "shop@example.org",
        "subject": "Summer sale",
        "internal_ms": str(
            int((datetime.now(UTC) - timedelta(days=1000)).timestamp() * 1000)
        ),
        "labels": "INBOX|CATEGORY_UPDATES",
        "unsubscribe": "1",
    }
    return tmp_path, settings, row


@pytest.mark.parametrize(
    "subject",
    [
        "Receipt",
        "Your RECEIPTS",
        "Your e-receipt",
        "Paid invoice #123",
        "INVOICE",
        "Order confirmation",
        "Your order was received",
        "Order placed",
        "Purchase confirmation",
        "Purchase receipt",
        "Payment confirmation",
        "Payment received",
        "Billing statement",
        "Account statements",
        "Transaction confirmed",
        "Shipping confirmation",
        "Shipment receipt",
        "Your order #123 has shipped",
        "Order—confirmed",
        "Thank you for your order",
        "=?utf-8?Q?Your_order_confirmation?=",
        "=?utf-8?B?UmVjZWlwdA==?=",
    ],
)
def test_transactional_formats(subject):
    assert is_receipt(subject)


@pytest.mark.parametrize(
    "labels",
    [
        "INBOX|CATEGORY_UPDATES",
        "INBOX|CATEGORY_PROMOTIONS",
        "CATEGORY_PERSONAL",
        "INBOX",
    ],
)
def test_receipt_protection_precedes_category_and_sender(setup, labels):
    _, settings, row = setup
    receipt = row | {"labels": labels, "subject": "Order received"}
    assert protection_reason(receipt) == "receipt_protected"
    assert not eligible(receipt, settings, set(), {row["sender"]: "trash"})


def test_same_sender_promotion_remains_eligible(setup):
    _, settings, row = setup
    assert eligible(row, settings, set(), {row["sender"]: "trash"})
    assert (
        not is_receipt("Preview our shipping confirmation designs") is False
    )  # conservative match
    assert not is_receipt("A spectacular sale for you")
    assert not eligible(
        row | {"subject": "Order placed"}, settings, set(), {row["sender"]: "trash"}
    )


def test_older_config_defaults_to_protected(setup):
    root, _, _ = setup
    path = root / "data/config.toml"
    path.write_text(path.read_text().replace("protect_receipts = true\n", ""))
    assert load_settings(path).protect_receipts is True
    path.write_text(
        path.read_text().replace(
            "[protection]", "[protection]\nprotect_receipts = false"
        )
    )
    with pytest.raises(ValueError, match="Permanent receipt"):
        load_settings(path)


@pytest.mark.parametrize(
    "change",
    [
        {"subject": ""},
        {"subject": None},
        {"internal_ms": "bad"},
        {"subject": "=?nonsense?B?UmVjZWlwdA==?="},
        {"labels": None},
        {"id": ""},
    ],
)
def test_invalid_metadata_is_ineligible(setup, change):
    _, settings, row = setup
    assert not eligible(row | change, settings, set(), {row["sender"]: "trash"})


@pytest.mark.parametrize("stage", ["before_confirmation", "after_confirmation"])
@pytest.mark.parametrize(
    "change",
    ["receipt", "missing", "malformed", "unavailable", "starred", "protected_label"],
)
def test_final_check_never_trashes_changed_message(
    setup, monkeypatch, capsys, stage, change
):
    root, settings, row = setup
    settings = replace(settings, protected_labels=("Label_records",))
    storage.write_csv(root / "output/inventory.csv", storage.INVENTORY_FIELDS, [row])
    monkeypatch.setattr(gmail_client, "connect", lambda _: object())
    monkeypatch.setattr(gmail_client, "list_ids", lambda *a: iter(["A1"]))
    calls = 0

    def metadata(*args):
        nonlocal calls
        calls += 1
        if stage == "after_confirmation" and calls == 1:
            return row.copy()
        if change == "unavailable":
            raise OSError("simulated failure")
        if change == "malformed":
            return None
        return (
            row
            | {
                "receipt": {"subject": "Order received"},
                "missing": {"subject": ""},
                "starred": {"labels": row["labels"] + "|STARRED"},
                "protected_label": {"labels": row["labels"] + "|Label_records"},
            }[change]
        )

    monkeypatch.setattr(gmail_client, "metadata", metadata)
    mutation = MagicMock()
    monkeypatch.setattr(gmail_client, "trash", mutation)
    monkeypatch.setattr("builtins.input", lambda _: "TRASH 1")
    cleanup.trash(
        root, settings, set(), {row["sender"]: "trash"}, execute=True, limit=1
    )
    mutation.assert_not_called()
    assert "Skipped A1:" in capsys.readouterr().out
    assert not (root / "output/cleanup_log.csv").exists()


def test_reports_separate_receipts_from_candidates(setup):
    root, settings, row = setup
    storage.write_csv(
        root / "output/inventory.csv",
        storage.INVENTORY_FIELDS,
        [row, row | {"id": "A2", "subject": "Order received"}],
    )
    decisions = {row["sender"]: "trash"}
    reports.report(root, settings, set(), decisions)
    assert [r["id"] for r in reports.candidates(root, settings, set(), decisions)] == [
        "A1"
    ]
    protected = storage.read_csv(
        root / "output/protected_messages.csv",
        (*storage.INVENTORY_FIELDS, "protection_reason"),
    )
    assert protected[0]["id"] == "A2"
    assert protected[0]["protection_reason"] == "receipt_protected"


@pytest.mark.parametrize(
    "subjects, expected",
    [
        (["=?utf-8?B?UmVjZWlwdA==?="], "Receipt"),
        ([], ""),
        (["Sale", "Receipt"], ""),
        (["=?badcharset?B?UmVjZWlwdA==?="], ""),
    ],
)
def test_adapter_decodes_or_rejects_ambiguous_subject(subjects, expected):
    api = MagicMock()
    api.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "id": "A",
        "payload": {
            "headers": [{"name": "Subject", "value": value} for value in subjects]
        },
    }
    assert gmail_client.metadata(api, "A")["subject"] == expected
