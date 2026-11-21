"""Conservative, data-driven selection rules. No network operations."""

import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.header import decode_header
from pathlib import Path
import re
import tomllib
import unicodedata

CATEGORIES = {
    "CATEGORY_PROMOTIONS": "promotions",
    "CATEGORY_SOCIAL": "social",
    "CATEGORY_UPDATES": "updates",
    "CATEGORY_FORUMS": "forums",
}

# Conservative core protections; users can add terms in config.toml.
CORE_TERMS = (
    "receipt",
    "donat",
    "contribut",
    "invoice",
    "payment",
    "statement",
    "tax",
    "membership",
    "renewal",
    "purchase",
    "order confirmation",
    "refund",
    "bank",
    "security alert",
    "verification",
    "google+",
    "google plus",
)


@dataclass(frozen=True)
class Settings:
    """Validated configuration for cleanup and protection rules."""

    dry_run: bool
    batch_size: int
    minimum_age_days: int
    categories: tuple[str, ...]
    protect_starred: bool
    protect_important: bool
    protect_attachments: bool
    protect_sent_by_me: bool
    subject_terms: tuple[str, ...]
    protected_labels: tuple[str, ...] = ()
    own_addresses: tuple[str, ...] = ()
    protect_receipts: bool = True


def _boolean(section: dict, name: str) -> bool:
    value = section.get(name)
    if type(value) is not bool:
        raise ValueError(f"Expected a true/false value for {name}")
    return value


def _positive_int(section: dict, name: str) -> int:
    value = section.get(name)
    if type(value) is not int or value < 1:
        raise ValueError(f"Expected a positive integer for {name}")
    return value


def load_settings(path: Path) -> Settings:
    """Load and validate safety-sensitive TOML configuration."""
    with path.open("rb") as stream:
        root = tomllib.load(stream)

    cleanup = root["cleanup"]
    protection = root["protection"]
    categories_section = root["categories"]

    if not all(
        isinstance(value, dict) for value in (cleanup, protection, categories_section)
    ):
        raise ValueError("Invalid config.toml sections")

    if cleanup.get("require_approved_sender") is not True:
        raise ValueError("0.1.0 requires require_approved_sender = true")

    if protection.get("protect_receipts", True) is not True:
        raise ValueError(
            "Permanent receipt protection requires protect_receipts = true"
        )

    names = categories_section.get("candidates")
    if (
        not isinstance(names, list)
        or not names
        or any(not isinstance(name, str) or name not in CATEGORIES for name in names)
    ):
        raise ValueError(f"Allowed Gmail categories: {', '.join(CATEGORIES)}")

    additions = protection.get("subject_contains", [])
    if not isinstance(additions, list) or any(
        not isinstance(x, str) for x in additions
    ):
        raise ValueError("protection.subject_contains must be a list of strings")

    label_ids = protection.get("label_ids", [])
    addresses = protection.get("own_addresses", [])
    for name, values in (("label_ids", label_ids), ("own_addresses", addresses)):
        if not isinstance(values, list) or any(
            not isinstance(v, str) or not v.strip() for v in values
        ):
            raise ValueError(f"protection.{name} must contain nonempty strings")

    return Settings(
        protect_receipts=True,
        protected_labels=tuple(label_ids),
        own_addresses=tuple(a.strip().casefold() for a in addresses),
        dry_run=_boolean(cleanup, "dry_run"),
        batch_size=_positive_int(cleanup, "batch_size"),
        minimum_age_days=_positive_int(cleanup, "minimum_age_days"),
        categories=tuple(names),
        protect_starred=_boolean(protection, "protect_starred"),
        protect_important=_boolean(protection, "protect_important"),
        protect_attachments=_boolean(protection, "protect_attachments"),
        protect_sent_by_me=_boolean(protection, "protect_sent_by_me"),
        subject_terms=CORE_TERMS + tuple(x.casefold() for x in additions if x),
    )


def read_senders(
    path: Path,
    fields: tuple[str, ...],
) -> list[dict[str, str]]:
    """Reject ambiguous data, including duplicate sender entries."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)

        if reader.fieldnames != list(fields):
            raise ValueError(f"{path.name}: required columns are {', '.join(fields)}")

        rows = list(reader)

    seen: set[str] = set()

    for row in rows:
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"{path.name}: malformed CSV row")

        address = row["email"].strip().casefold()

        if (
            not address
            or address.count("@") != 1
            or any(x.isspace() for x in address)
            or any(x in address for x in '<>(),;:"')
            or not all(address.split("@"))
        ):
            raise ValueError(f"{path.name}: invalid email address: {address!r}")

        if address in seen:
            raise ValueError(f"{path.name}: duplicate sender: {address}")

        seen.add(address)
        row["email"] = address

    return rows


def protected_sender_reasons(data: Path) -> dict[str, str]:
    """Load normalized protected addresses and their user-maintained reasons."""
    return {
        row["email"]: row["reason"].strip()
        for row in read_senders(data / "senders_protected.csv", ("email", "reason"))
    }


class SenderDecisions(dict[str, str]):
    """Keep explicit decisions separate from indexed permanent approvals."""

    def __init__(self, always_delete: dict[str, str]) -> None:
        """Store normalized permanent approval reasons without changing decisions."""
        super().__init__()
        self.always_delete = always_delete


def always_delete_reasons(data: Path) -> dict[str, str]:
    """Load the optional permanent list once; reject invalid existing files."""
    path = data / "senders_always_delete.csv"
    if not path.exists():
        return {}
    return {
        row["email"]: row["reason"].strip()
        for row in read_senders(path, ("email", "reason"))
    }


def sender_approval(sender: str, decisions: dict[str, str]) -> str:
    """Resolve approval while explicit keep and review decisions fail closed."""
    sender = sender.strip().casefold()
    permanent = (
        isinstance(decisions, SenderDecisions) and sender in decisions.always_delete
    )
    decision = decisions.get(sender, "")
    if decision in {"keep", "review"}:
        return (
            f"conflict: permanent approval with {decision}" if permanent else decision
        )
    if decision not in {"", "trash"}:
        return "invalid decision"
    if permanent:
        return "permanently approved"
    return "individually approved" if decision == "trash" else "undecided"


def sender_rules(
    data: Path,
) -> tuple[set[str], SenderDecisions]:
    """Read protected senders, explicit decisions, and optional permanent approvals."""
    protected_reasons = protected_sender_reasons(data)

    decision_rows = read_senders(
        data / "sender_decisions.csv",
        ("email", "decision", "notes"),
    )

    decisions = SenderDecisions(always_delete_reasons(data))

    for row in decision_rows:
        value = row["decision"].strip().casefold()

        if value not in {"", "keep", "review", "trash"}:
            raise ValueError(f"Invalid decision for {row['email']}: {value!r}")

        decisions[row["email"]] = value

    protected = set(protected_reasons)

    return protected, decisions


def gmail_query(settings: Settings) -> str:
    """Search the active Inbox using Gmail's category filters."""
    categories = [f"category:{CATEGORIES[c]}" for c in settings.categories]

    if len(categories) == 1:
        category_query = categories[0]
    else:
        category_query = "{" + " ".join(categories) + "}"

    parts = [
        "in:inbox",
        category_query,
        f"older_than:{settings.minimum_age_days}d",
    ]

    if settings.protect_starred:
        parts.append("-is:starred")

    if settings.protect_important:
        parts.append("-is:important")

    if settings.protect_attachments:
        parts.append("-has:attachment")

    if settings.protect_sent_by_me:
        parts.append("-from:me")

    return " ".join(parts)


# REQ: Sender approval must never override transactional record protection.
# WHY: Normalize punctuation before matching bounded, deterministic patterns.
RECEIPT_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:receipts?|invoices?|e ?receipts?)\b",
        (
            r"\b(?:orders?|purchases?|payments?|transactions?|shipping|shipments?)\b"
            r"(?:\s+\w+){0,4}\s+(?:confirmations?|confirmed|received|placed|paid|processed|successful|completed|shipped|delivered)\b"
        ),
        (
            r"\b(?:confirmations?|confirmed)\s+(?:of\s+|for\s+)?(?:your\s+)?"
            r"(?:orders?|purchases?|payments?|transactions?|shipping|shipments?)\b"
        ),
        r"\b(?:billing|account|bank|credit card)\s+statements?\b",
        r"\b(?:thanks|thank you)\s+for\s+(?:your\s+)?(?:order|purchase|payment)\b",
    )
)


def decoded_subject(value: object) -> str:
    """Decode a Subject header strictly; reject missing or ambiguous text."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing Subject header")
    try:
        text = "".join(
            part.decode(charset or "ascii", errors="strict")
            if isinstance(part, bytes)
            else part
            for part, charset in decode_header(value)
        )
    except (LookupError, UnicodeError, ValueError) as exc:
        raise ValueError("Uninterpretable Subject header") from exc
    if not text.strip() or "=?" in text or "\ufffd" in text or "\x00" in text:
        raise ValueError("Uninterpretable Subject header")
    return text


def is_receipt(subject: str) -> bool:
    """Recognize transactional subjects without inspecting message bodies."""
    text = unicodedata.normalize("NFKC", decoded_subject(subject)).casefold()
    text = re.sub(r"[^\w]+|_", " ", text)
    return any(pattern.search(text) for pattern in RECEIPT_PATTERNS)


def protection_reason(row: dict[str, str]) -> str:
    """Explain receipt or invalid-metadata protection before other eligibility rules."""
    for name in ("id", "sender", "subject", "internal_ms", "labels"):
        if not isinstance(row.get(name), str) or not row[name].strip():
            return f"metadata_invalid: {name}"
    try:
        if is_receipt(row["subject"]):
            return "receipt_protected"
        datetime.fromtimestamp(int(row["internal_ms"]) / 1000, tz=UTC)
    except ValueError, TypeError, OverflowError, OSError:
        return "metadata_invalid: subject or date"
    return ""


def eligible(
    row: dict[str, str],
    settings: Settings,
    protected: set[str],
    decisions: dict[str, str],
    *,
    now: datetime | None = None,
) -> bool:
    """Fail closed: only approved, protection-safe messages qualify."""
    if protection_reason(row):
        return False

    sender = row.get("sender", "").strip().casefold()

    if (
        not sender
        or sender in protected
        or sender_approval(sender, decisions)
        not in {"permanently approved", "individually approved"}
    ):
        return False

    labels = set(row.get("labels", "").split("|"))

    if labels.intersection(settings.protected_labels):
        return False

    if settings.protect_sent_by_me and sender in settings.own_addresses:
        return False

    if not row.get("id") or not row.get("subject", "").strip():
        return False

    if "INBOX" not in labels:
        return False

    if labels & {"TRASH", "SPAM", "DRAFT"}:
        return False

    if not labels.intersection(settings.categories):
        return False

    if settings.protect_starred and "STARRED" in labels:
        return False

    if settings.protect_important and "IMPORTANT" in labels:
        return False

    if settings.protect_sent_by_me and "SENT" in labels:
        return False

    # Marketing-list evidence is required.
    if row.get("unsubscribe") != "1":
        return False

    subject = decoded_subject(row["subject"]).casefold()

    if any(term in subject for term in settings.subject_terms):
        return False

    try:
        milliseconds = int(row["internal_ms"])
        when = datetime.fromtimestamp(
            milliseconds / 1000,
            tz=UTC,
        )
    except KeyError, ValueError, OverflowError, OSError:
        return False

    current = now or datetime.now(UTC)

    return when < current - timedelta(days=settings.minimum_age_days)
