"""Synthetic Gmail pagination, durable cursor recovery, and safety regressions."""

from collections import Counter
from contextlib import closing
from dataclasses import replace
import json
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tidy_gmail import cli, inventory, reports, scan_state, storage
from tidy_gmail import gmail_client as gmail
from tidy_gmail.rules import load_settings, sender_rules


class ApiError(Exception):
    def __init__(self, status, reason="invalidArgument"):
        self.resp = SimpleNamespace(status=status)
        self.content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()


class Request:
    def __init__(self, operation):
        self.operation = operation

    def execute(self):
        return self.operation()


class FakeGmail:
    def __init__(self, pages):
        self.pages = pages
        self.list_calls = []
        self.metadata_calls = Counter()
        self.errors = {}
        self.subjects = {}
        self.senders = {}
        self.account = "synthetic@example.org"

    def users(self):
        return self

    def messages(self):
        return self

    def getProfile(self, **kwargs):
        return Request(lambda: {"emailAddress": self.account})

    def list(self, **kwargs):
        assert kwargs["maxResults"] == 500
        assert kwargs["includeSpamTrash"] is False
        token = kwargs.get("pageToken")
        self.list_calls.append(token)

        def result():
            value = self.pages[token]
            if isinstance(value, BaseException):
                raise value
            ids, next_token = value
            return {
                "messages": [{"id": item} for item in ids],
                **({"nextPageToken": next_token} if next_token else {}),
            }

        return Request(result)

    def get(self, **kwargs):
        assert kwargs["format"] == "metadata"
        message_id = kwargs["id"]

        def result():
            self.metadata_calls[message_id] += 1
            if message_id in self.errors:
                raise self.errors[message_id]
            return {
                "id": message_id,
                "threadId": "T" + message_id,
                "internalDate": "1000000000000",
                "labelIds": ["INBOX", "CATEGORY_PROMOTIONS"],
                "payload": {
                    "headers": [
                        {
                            "name": "From",
                            "value": self.senders.get(message_id, "offers@example.org"),
                        },
                        {
                            "name": "Subject",
                            "value": self.subjects.get(message_id, "Sale"),
                        },
                        {
                            "name": "List-Unsubscribe",
                            "value": "<mailto:leave@example.org>",
                        },
                    ]
                },
            }

        return Request(result)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    storage.init(tmp_path, confirm=True)
    api = FakeGmail({None: (["A", "B", "C"], "next"), "next": (["C", "D", "E"], None)})
    monkeypatch.setattr(gmail, "connect", lambda _: api)
    return tmp_path, load_settings(tmp_path / "data/config.toml"), api


def progress(root):
    db = scan_state.read_checkpoint(root)
    try:
        return json.loads(db.execute("SELECT payload FROM progress").fetchone()[0])
    finally:
        db.close()


def test_successive_limits_resume_midpage_and_deduplicate(setup):
    root, settings, api = setup
    inventory.scan(root, settings, limit=2)
    assert progress(root)["offset"] == 2
    assert api.list_calls == [None]
    assert len(inventory.read_inventory(root)) == 2
    inventory.scan(root, settings, limit=2)
    assert len(inventory.read_inventory(root)) == 4
    assert api.list_calls == [None, "next"]
    inventory.scan(root, settings, limit=2)
    assert progress(root)["complete"] is True
    assert len(inventory.read_inventory(root)) == 5
    assert set(api.metadata_calls.values()) == {1}
    inventory.scan(root, settings, limit=2)
    assert api.list_calls == [None, "next"]


def test_ctrl_c_preserves_completed_work_and_cli_exit(setup):
    root, settings, api = setup
    api.errors["B"] = KeyboardInterrupt()
    assert cli.main(["--workspace", str(root), "scan", "--limit", "5"]) == 130
    assert progress(root)["offset"] == 1
    assert progress(root)["complete"] is False
    assert [row["id"] for row in inventory.read_inventory(root)] == ["A"]
    api.errors.clear()
    inventory.scan(root, settings, limit=10)
    assert api.metadata_calls["A"] == 1
    assert progress(root)["complete"] is True


def test_transaction_rollback_does_not_advance_cursor(setup, monkeypatch):
    root, settings, _ = setup
    state = scan_state.ScanState(root, settings)
    state.load_page(["A", "B"], None)
    row = {key: "value" for key in storage.INVENTORY_FIELDS} | {"id": "A"}
    original = state.save

    def fail_after_save():
        original()
        raise KeyboardInterrupt

    monkeypatch.setattr(state, "save", fail_after_save)
    with pytest.raises(KeyboardInterrupt):
        state.record("A", row)
    assert state.state["offset"] == 0
    assert not state.known("A")
    state.close()
    assert progress(root)["offset"] == 0


@pytest.mark.parametrize("commit", [False, True])
def test_process_crash_recovers_only_committed_metadata(setup, commit):
    root, settings, api = setup
    state = scan_state.ScanState(root, settings)
    state.load_page(["A", "B", "C"], "next")
    state.close()
    script = """import json, os, sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
state = json.loads(connection.execute("SELECT payload FROM progress").fetchone()[0])
row = {"id":"A","thread_id":"TA","sender":"offers@example.org","subject":"Sale","internal_ms":"1000000000000","labels":"INBOX|CATEGORY_PROMOTIONS","unsubscribe":"1"}
connection.execute("BEGIN IMMEDIATE")
connection.execute("INSERT INTO messages VALUES (?, ?, '')", ("A", json.dumps(row)))
state["offset"] = 1
connection.execute("UPDATE progress SET payload=?", (json.dumps(state),))
if sys.argv[2] == "yes": connection.commit()
os._exit(23)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(scan_state.checkpoint_path(root)),
            "yes" if commit else "no",
        ],
        check=False,
    )
    assert result.returncode == 23
    inventory.scan(root, settings, limit=10)
    assert api.metadata_calls["A"] == (0 if commit else 1)
    assert len(inventory.read_inventory(root)) == 5
    assert progress(root)["complete"] is True


def test_invalid_token_stops_without_discarding_results(setup):
    root, settings, api = setup
    inventory.scan(root, settings, limit=3)
    api.pages["next"] = ApiError(400)
    with pytest.raises(ValueError, match="pagination token"):
        inventory.scan(root, settings, limit=3)
    assert len(inventory.read_inventory(root)) == 3
    assert not progress(root)["complete"]
    api.pages["next"] = (["D"], None)
    inventory.scan(root, settings, limit=10, restart=True)
    assert progress(root)["complete"]
    archives = list((root / ".local/scan-archives").glob("*.sqlite"))
    assert len(archives) == 1
    with closing(sqlite3.connect(archives[0])) as db:
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 3


def test_changed_settings_require_explicit_archived_restart(setup):
    root, settings, api = setup
    inventory.scan(root, settings, limit=1)
    before = api.list_calls.copy()
    changed = replace(settings, minimum_age_days=365)
    with pytest.raises(ValueError, match="settings changed"):
        inventory.scan(root, changed, limit=1)
    assert api.list_calls == before
    assert "Partial" in scan_state.coverage(root, changed)
    inventory.scan(root, changed, limit=2, restart=True)
    assert len(inventory.read_inventory(root)) == 2
    assert progress(root)["query"].endswith("-from:me")
    assert "older_than:365d" in progress(root)["query"]


def test_effective_query_change_is_incompatible(setup, monkeypatch):
    root, settings, _ = setup
    inventory.scan(root, settings, limit=1)
    monkeypatch.setattr(scan_state, "gmail_query", lambda _: "different query")
    with pytest.raises(ValueError, match="settings changed"):
        inventory.scan(root, settings, limit=1)


def test_other_account_cannot_reuse_checkpoint(setup):
    root, settings, api = setup
    inventory.scan(root, settings, limit=1)
    api.account = "different@example.org"
    with pytest.raises(ValueError, match="different Gmail account"):
        inventory.scan(root, settings, limit=1, restart=True)
    assert len(inventory.read_inventory(root)) == 1


def test_empty_pages_and_completion(setup):
    root, settings, api = setup
    api.pages = {None: ([], "next"), "next": ([], None)}
    inventory.scan(root, settings, limit=1)
    assert progress(root)["complete"]
    assert inventory.read_inventory(root) == []


def test_repeated_token_does_not_loop(setup):
    root, settings, api = setup
    api.pages = {None: ([], "next"), "next": ([], "next")}
    with pytest.raises(ValueError, match="repeated page token"):
        inventory.scan(root, settings, limit=1)
    assert not progress(root)["complete"]


def test_legacy_inventory_is_archived_only_on_explicit_restart(setup):
    root, settings, _ = setup
    path = root / "output/inventory.csv"
    original = b"id,thread_id,sender,subject,internal_ms,labels,unsubscribe\n"
    path.write_bytes(original)
    with pytest.raises(ValueError, match="no checkpoint"):
        inventory.scan(root, settings, limit=1)
    assert path.read_bytes() == original
    inventory.scan(root, settings, limit=1, restart=True)
    assert next((root / ".local/scan-archives").glob("*.csv")).read_bytes() == original


def test_sender_decisions_and_message_protections_survive_scan(setup, capsys):
    root, settings, api = setup
    decisions_path = root / "data/sender_decisions.csv"
    original = b"email,decision,notes\noffers@example.org,keep,do not change\n"
    decisions_path.write_bytes(original)
    (root / "data/senders_always_delete.csv").write_text(
        "email,reason\nmerchant@example.org,reviewed\n"
    )
    (root / "data/senders_protected.csv").write_text(
        "email,reason\nfamily@example.org,family\n"
    )
    api.senders = {
        "A": "merchant@example.org",
        "B": "family@example.org",
        "C": "merchant@example.org",
    }
    api.subjects["A"] = "Order confirmation"
    permanent = (root / "data/senders_always_delete.csv").read_bytes()
    protected_file = (root / "data/senders_protected.csv").read_bytes()
    inventory.scan(root, settings, limit=2)
    protected, decisions = sender_rules(root / "data")
    reports.report(root, settings, protected, decisions)
    assert "Partial" in capsys.readouterr().out
    assert reports.candidates(root, settings, protected, decisions) == []
    inventory.scan(root, settings, limit=10)
    protected, decisions = sender_rules(root / "data")
    assert [
        row["id"] for row in reports.candidates(root, settings, protected, decisions)
    ] == ["C"]
    assert "Complete" in capsys.readouterr().out
    assert decisions_path.read_bytes().startswith(original)
    assert decisions_path.read_text().count("merchant@example.org") == 1
    assert (root / "data/senders_always_delete.csv").read_bytes() == permanent
    assert (root / "data/senders_protected.csv").read_bytes() == protected_file


def test_lock_rejects_concurrent_scan(setup):
    root, settings, _ = setup
    with scan_state.scan_lock(root), pytest.raises(ValueError, match="Another scan"):
        inventory.scan(root, settings, limit=1)


def test_unavailable_message_is_recorded_not_retried_forever(setup):
    root, settings, api = setup
    api.errors["B"] = ApiError(404)
    inventory.scan(root, settings, limit=10)
    assert progress(root)["complete"]
    assert len(inventory.read_inventory(root)) == 4
    assert "not_found" in (root / "output/scan_unavailable.csv").read_text()


def test_large_scan_uses_each_id_once(setup):
    root, settings, api = setup
    count = 10001
    api.pages = {}
    for start in range(0, count, 500):
        api.pages[str(start) if start else None] = (
            [str(i) for i in range(start, min(start + 500, count))],
            str(start + 500) if start + 500 < count else None,
        )
    inventory.scan(root, settings, limit=5001)
    inventory.scan(root, settings, limit=5001)
    assert len(inventory.read_inventory(root)) == count
    assert len(api.metadata_calls) == count
    assert set(api.metadata_calls.values()) == {1}
    assert progress(root)["complete"]


@pytest.mark.parametrize(
    "error",
    [ApiError(429), ApiError(503), ApiError(403, "rateLimitExceeded"), TimeoutError()],
)
def test_transient_reads_retry_with_bounded_backoff(monkeypatch, error):
    waits = []
    monkeypatch.setattr(gmail.time, "sleep", waits.append)
    monkeypatch.setattr(gmail.random, "random", lambda: 0)
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise error
        return "ok"

    assert gmail.read_with_retry(operation) == "ok"
    assert waits == [1, 2]


def test_retry_exhaustion_is_bounded(monkeypatch):
    waits = []
    monkeypatch.setattr(gmail.time, "sleep", waits.append)

    def operation():
        raise ApiError(503)

    with pytest.raises(ApiError):
        gmail.read_with_retry(operation)
    assert len(waits) == 5


def test_permanent_error_is_not_retried(setup, monkeypatch):
    root, settings, api = setup
    waits = []
    monkeypatch.setattr(gmail.time, "sleep", waits.append)
    api.errors["B"] = ApiError(403, "domainPolicy")
    with pytest.raises(ValueError, match="Scan stopped"):
        inventory.scan(root, settings, limit=10)
    assert waits == []
    assert progress(root)["offset"] == 1
    assert not progress(root)["complete"]


def test_export_failure_does_not_lose_committed_inventory(setup, monkeypatch):
    root, settings, api = setup
    original = storage.write_csv

    def fail_export(*args, **kwargs):
        raise OSError("simulated disk error")

    monkeypatch.setattr(storage, "write_csv", fail_export)
    with pytest.raises(OSError, match="disk error"):
        inventory.scan(root, settings, limit=10)
    assert progress(root)["complete"]
    assert len(inventory.read_inventory(root)) == 5
    requests = api.metadata_calls.copy()
    monkeypatch.setattr(storage, "write_csv", original)
    inventory.scan(root, settings, limit=10)
    assert api.metadata_calls == requests
    assert (
        len(storage.read_csv(root / "output/inventory.csv", storage.INVENTORY_FIELDS))
        == 5
    )


def test_atomic_sender_discovery_preserves_file_on_replace_failure(setup, monkeypatch):
    root, _, _ = setup
    path = root / "data/sender_decisions.csv"
    original = b"email,decision,notes\nold@example.org,keep,personal"
    path.write_bytes(original)
    replace_file = storage.os.replace

    def fail_replace(*args):
        raise OSError("simulated interruption")

    monkeypatch.setattr(storage.os, "replace", fail_replace)
    with pytest.raises(OSError):
        storage.append_senders(path, ["new@example.org"])
    assert path.read_bytes() == original
    monkeypatch.setattr(storage.os, "replace", replace_file)
    storage.append_senders(path, ["new@example.org"])
    assert path.read_bytes().startswith(original + b"\n")


def test_report_files_label_partial_and_complete(setup):
    root, settings, _ = setup
    inventory.scan(root, settings, limit=1)
    protected, decisions = sender_rules(root / "data")
    reports.report(root, settings, protected, decisions)
    reports.candidates(root, settings, protected, decisions)
    for name in ("report_status.csv", "candidates_status.csv"):
        assert "Partial" in (root / "output" / name).read_text()
    inventory.scan(root, settings, limit=10)
    reports.report(root, settings, protected, decisions)
    assert "Complete" in (root / "output/report_status.csv").read_text()
    assert "Partial" in (root / "output/candidates_status.csv").read_text()


def test_malformed_page_never_marks_scan_complete(setup):
    root, settings, api = setup
    api.pages = {None: ([None], None)}
    with pytest.raises(ValueError, match="Missing Gmail message ID"):
        inventory.scan(root, settings, limit=1)
    assert not progress(root)["complete"]
    assert inventory.read_inventory(root) == []


def test_unsupported_checkpoint_is_not_replaced(setup):
    root, settings, _ = setup
    inventory.scan(root, settings, limit=1)
    db = sqlite3.connect(scan_state.checkpoint_path(root))
    try:
        value = progress(root)
        value["schema"] = 999
        with db:
            db.execute("UPDATE progress SET payload=?", (json.dumps(value),))
    finally:
        db.close()
    with pytest.raises(ValueError, match="Unsupported"):
        inventory.scan(root, settings, limit=1, restart=True)
    assert len(inventory.read_inventory(root)) == 1
