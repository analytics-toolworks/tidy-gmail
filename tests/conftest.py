"""Prevent tests from authorizing a real Gmail account."""

import pytest

from tidy_gmail import auth, gmail_client


@pytest.fixture(autouse=True)
def block_gmail(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must supply a simulated Gmail client")

    monkeypatch.setattr(auth, "connect", blocked)
    monkeypatch.setattr(gmail_client, "connect", blocked)
