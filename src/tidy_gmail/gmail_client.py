"""Minimal Gmail API adapter; never retrieves message bodies."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from email.utils import parseaddr
import hashlib
import json
import random
import time
from typing import Any

from .auth import SCOPES, connect  # noqa: F401
from .rules import decoded_subject

HEADERS = [
    "From",
    "Subject",
    "List-Unsubscribe",
]


def read_with_retry[T](operation: Callable[[], T]) -> T:
    """Retry read-only requests at most five times after transient failures."""
    for attempt in range(6):
        try:
            return operation()
        except Exception as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            rate_limited = False
            if status == 403:
                try:
                    details = json.loads(getattr(exc, "content", b"{}"))
                    rate_limited = any(
                        item.get("reason")
                        in {"rateLimitExceeded", "userRateLimitExceeded"}
                        for item in details.get("error", {}).get("errors", [])
                    )
                except ValueError, TypeError, AttributeError:
                    pass
            transient = (
                isinstance(exc, (ConnectionError, TimeoutError, OSError))
                or status in {429, 500, 502, 503, 504}
                or rate_limited
            )
            if attempt == 5 or not transient:
                raise
            delay = 2**attempt + random.random()
            print(
                f"Temporary Gmail read failure; retry {attempt + 1}/5 in {delay:.1f}s"
            )
            time.sleep(delay)
    raise RuntimeError("Unreachable retry state")


def scan_account(api: Any) -> str:
    """Bind checkpoints to a mailbox without retaining its email address."""
    profile = read_with_retry(lambda: api.users().getProfile(userId="me").execute())
    address = profile.get("emailAddress")
    if not isinstance(address, str) or "@" not in address:
        raise ValueError("Missing Gmail account identity")
    return hashlib.sha256(address.strip().casefold().encode()).hexdigest()


def list_page(
    api: Any, query: str, page_token: str | None = None
) -> tuple[list[str], str | None]:
    """Fetch one validated page, respecting Gmail's maximum of 500 messages."""
    params: dict[str, Any] = {
        "userId": "me",
        "q": query,
        "maxResults": 500,
        "includeSpamTrash": False,
    }
    if page_token:
        params["pageToken"] = page_token
    result = read_with_retry(lambda: api.users().messages().list(**params).execute())
    messages = result.get("messages", [])
    token = result.get("nextPageToken")
    if not isinstance(messages, list) or (
        token is not None and (not isinstance(token, str) or not token)
    ):
        raise ValueError("Malformed Gmail pagination response")
    ids = []
    for item in messages:
        message_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(message_id, str) or not message_id:
            raise ValueError("Missing Gmail message ID in page")
        ids.append(message_id)
    return ids, token


def list_ids(
    api: Any,
    query: str,
    *,
    limit: int | None = None,
) -> Iterator[str]:
    """Page Gmail search results, excluding Spam and Trash."""
    page_token: str | None = None
    seen: set[str] = set()

    while True:
        params: dict[str, Any] = {
            "userId": "me",
            "q": query,
            "maxResults": 500,
            "includeSpamTrash": False,
        }

        if page_token:
            params["pageToken"] = page_token

        result = api.users().messages().list(**params).execute()

        for item in result.get("messages", []):
            message_id = item["id"]

            if message_id in seen:
                continue

            seen.add(message_id)
            yield message_id

            if limit is not None and len(seen) >= limit:
                return

        page_token = result.get("nextPageToken")

        if not page_token:
            return


def metadata(
    api: Any,
    message_id: str,
) -> dict[str, str]:
    """Read headers, labels, and dates without retrieving MIME bodies."""
    result = (
        api.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=HEADERS,
        )
        .execute()
    )

    headers = {
        item["name"].casefold(): item.get("value", "")
        for item in result.get("payload", {}).get("headers", [])
    }

    # REQ: Duplicate Subject headers are ambiguous; never choose one silently.
    subjects = [
        item.get("value")
        for item in result.get("payload", {}).get("headers", [])
        if item.get("name", "").casefold() == "subject"
    ]
    try:
        subject = decoded_subject(subjects[0]) if len(subjects) == 1 else ""
    except ValueError:
        subject = ""

    sender = parseaddr(headers.get("from", ""))[1].strip().casefold()

    return {
        "id": result["id"],
        "thread_id": result.get("threadId", ""),
        "sender": sender,
        "subject": subject,
        "internal_ms": result.get("internalDate", ""),
        "labels": "|".join(sorted(result.get("labelIds", []))),
        "unsubscribe": ("1" if headers.get("list-unsubscribe") else "0"),
    }


def trash(api: Any, message_id: str) -> None:
    """Move one Gmail message to Trash."""
    (api.users().messages().trash(userId="me", id=message_id).execute())


def untrash(api: Any, message_id: str) -> None:
    """Remove one Gmail message from Trash."""
    (api.users().messages().untrash(userId="me", id=message_id).execute())


def add_inbox(api: Any, message_id: str) -> None:
    """Restore Inbox membership when required."""
    (
        api.users()
        .messages()
        .modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": ["INBOX"]},
        )
        .execute()
    )
