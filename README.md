# tidy-gmail

[![PyPI](https://img.shields.io/pypi/v/tidy-gmail?logo=pypi&label=pypi)](https://pypi.org/project/tidy-gmail/)
[![Docs Site](https://img.shields.io/badge/docs-site-blue?logo=github)](https://analytics-toolworks.github.io/tidy-gmail/)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https://raw.githubusercontent.com/analytics-toolworks/tidy-gmail/main/pyproject.toml&logo=python)](https://github.com/analytics-toolworks/tidy-gmail/blob/main/pyproject.toml)
![uv](https://img.shields.io/badge/uv-managed-DE5FE9)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[![CI](https://github.com/analytics-toolworks/tidy-gmail/actions/workflows/ci-python-zensical.yml/badge.svg?branch=main)](https://github.com/analytics-toolworks/tidy-gmail/actions/workflows/ci-python-zensical.yml)
[![Docs](https://github.com/analytics-toolworks/tidy-gmail/actions/workflows/deploy-zensical.yml/badge.svg?branch=main)](https://github.com/analytics-toolworks/tidy-gmail/actions/workflows/deploy-zensical.yml)
[![Links](https://github.com/analytics-toolworks/tidy-gmail/actions/workflows/links.yml/badge.svg?branch=main)](https://github.com/analytics-toolworks/tidy-gmail/actions/workflows/links.yml)
[![Dependabot](https://img.shields.io/badge/Dependabot-enabled-brightgreen.svg)](https://github.com/analytics-toolworks/tidy-gmail/security)

<img
src="https://raw.githubusercontent.com/analytics-toolworks/tidy-gmail/main/docs/images/profile.png"
alt="profile logo"
width="110">

> A local, data-driven Gmail cleanup and organization tool.

**tidy-gmail** is a Python command-line application for identifying,
reviewing, and removing unwanted Gmail messages while preserving
correspondence and records that may have value.

The application runs locally using `uvx`.
There is no need to clone the GitHub repository.

**Status:** Initial development.

## Purpose

Email accumulates.
Gmail's categories help organize messages,
but don't determine which messages are safe to delete.

**tidy-gmail** provides a configurable process for:

- Discovering frequent senders and large groups of messages.
- Using Gmail's existing categories and message metadata.
- Maintaining protected sender and approved cleanup lists.
- Applying explicit protection and classification rules.
- Producing reviewable reports before modification.
- Moving approved messages to Gmail Trash.
- Recording operations for auditing and restoration.

It does not equate age, unread status, or duplication
with permission to delete.

## Design Principles

- Local-first: user configuration and reports remain local.
- Data-driven: user decisions are maintained outside the code.
- Conservative: protection rules always take precedence.
- Explicit: unknown messages are preserved.
- Inspectable: proposed changes are reported before execution.
- Reversible: cleanup uses Gmail Trash, not permanent deletion.
- Auditable: completed operations are recorded.
- Testable: classification and execution are separate components.
- Portable: Windows and macOS use the same command interface.

The tool does not guarantee that every valuable message can
be identified automatically.
Users should back up important email before bulk cleanup.

## Quick Start

These instructions are for people using the published application.
You do not need Git or a source checkout.
[Install uv](https://docs.astral.sh/uv/getting-started/installation/),
then initialize and validate your local workspace:

```shell
uvx tidy-gmail init
uvx tidy-gmail doctor
```

`uvx` runs the published package, so unpublished changes in a local checkout
are not included. If you are developing or testing this repository,
follow [Development](docs/development.md) and use `uv run tidy-gmail`.

Initialization creates missing items and preserves existing files.
A successful `doctor` checks local configuration only;
it does not connect to Gmail or validate OAuth.

### Configure Protection

Before scanning, review `data/config.toml` and keep dry-run enabled.
Add trusted contacts and record senders to `data/senders_protected.csv`.
The first line must be exactly:

```csv
email,reason
```

The first line of `data/sender_decisions.csv` must be exactly:

```csv
email,decision,notes
```

Use comma-separated UTF-8 files without spaces in column names.
Header-only files are valid; zero-byte files are not.
Sender decisions may be blank, `keep`, `review`, or `trash`.
A `trash` decision or permanent-list membership approves a sender for consideration;
message protections still take precedence.
See [Protection settings](docs/index.md#protection) for labels,
own addresses, and subject terms.

### Connect and Inspect

Create your own Google Cloud desktop OAuth client with Gmail API enabled.
Save the downloaded client JSON as `.local/credentials.json`
inside your workspace. See [OAuth setup](docs/oauth.md).
Do not create `token.json` yourself; authorization creates it.

```shell
uvx tidy-gmail scan
uvx tidy-gmail report
```

The first scan prompts for Gmail authorization when needed.
Review the discovered senders in `data/sender_decisions.csv`,
then generate and inspect the proposed cleanup report:

```shell
uvx tidy-gmail candidates
uvx tidy-gmail trash --limit 10
```

The last command previews cleanup. To modify Gmail, first review
[Cleanup and recovery](docs/index.md#cleanup-and-recovery).
Execution requires disabling configured dry-run, passing `--execute`,
and confirming the displayed message count.

### Troubleshooting Local Configuration

If `doctor` reports required CSV columns, check the first line against
the examples above. `init` intentionally does not repair existing files.
For an empty file, add the required header. For a populated file,
back it up privately and correct its columns without discarding rows.
Then run `doctor` again.

`Workspace valid` means local configuration passed.
`OAuth not tested; no Gmail connection made` is expected at this stage.
Your next step is OAuth setup, followed by `scan`.

## Incremental and Resumable Scanning

Run bounded scans repeatedly to make progress through the eligible query:

```shell
uvx tidy-gmail scan --limit 1000
uvx tidy-gmail scan --limit 1000
```

The second command resumes where the first stopped and processes up to
1,000 additional unique message IDs. Duplicate IDs do not consume the limit.
`scan` without a limit keeps the existing default of 5,000 per invocation.
Continue until the status says `Complete - eligible query exhausted`.
A completed scan does not silently start over on the next invocation.

Press Ctrl+C to stop. Completed metadata is committed incrementally;
run the same command to resume. A request interrupted before its database
commit may be fetched again, but already committed IDs are not fetched again.
An unexpected process exit also preserves committed results.

To intentionally start a fresh traversal:

```shell
uvx tidy-gmail scan --restart --limit 1000
```

Restart archives the previous database under `.local/scan-archives/`
before resetting the active scan. It fetches fresh metadata from the beginning.
If upgrading from an older inventory without a checkpoint, the first scan
requires `--restart`; the old inventory CSV is archived rather than discarded.
Restart does not erase sender decisions, protected senders, or permanent approvals.

### Progress and Reports

Private state is stored in `.local/scan.sqlite` as a SQLite database.
It contains the effective query, configuration identity, a hashed mailbox
identity, pagination token, pending page IDs and position, and collected metadata.
The metadata is the same limited information used by the inventory CSV;
no message bodies or OAuth secrets are stored in the checkpoint.
Each metadata record and cursor advancement commits in the same transaction.
`.local/scan_lock.sqlite` prevents two scanners from writing simultaneously.

`output/inventory.csv` accumulates results across invocations.
`output/scan_status.csv` labels that export partial or complete.
`report` and `candidates` also save coverage in `report_status.csv` and
`candidates_status.csv`, display scan coverage, and read committed
checkpoint data, so a crash before CSV export does not hide completed work.
Run `scan` again to regenerate exports after a crash.
Reports and candidate files are regenerated only when their commands run.
Messages that disappear before metadata retrieval are recorded in
`output/scan_unavailable.csv` and counted separately from collected metadata.

### Changes and Recovery

Changes to the effective Gmail query or relevant protection settings require
an explicit `--restart`. Changing only the per-run limit, cleanup batch size,
or dry-run mode does not invalidate progress. Sender decisions and sender lists
are applied using their current values when reports and candidates are generated.
Keep one Gmail account per workspace; a different account cannot reuse its checkpoint.

If Gmail rejects a pagination token, scanning stops and preserves results.
Use `--restart` to archive them and begin a new traversal. It does not silently
jump past a rejected page. Temporary rate limits and network failures receive
up to five retries with increasing waits; exhausted failures preserve progress.

The scan covers the configured age, category, Inbox, attachment, and other
query filters. A Gmail category's total can therefore be much larger than
its eligible scan population. Receipts and protected senders can appear in
inventory while remaining excluded from cleanup candidates.
All existing cleanup safeguards and final pre-Trash checks remain in place.

Completion means Gmail returned no more pages for that traversal, not a
perfectly consistent snapshot. Messages may arrive, change, or disappear,
and relative age filters move with time. Use a fresh scan when needed.
Scanning streams pages and metadata to disk; reports retain their existing
in-memory processing. Keep private backups of checkpoints and recovery logs.

## Interface

The interface includes:

```shell
uvx tidy-gmail init
uvx tidy-gmail scan
uvx tidy-gmail report
uvx tidy-gmail candidates
uvx tidy-gmail trash
uvx tidy-gmail restore
```

The user maintains their own Gmail authorization,
configuration, and reports.

## Installation Requirements

[Install `uv`](https://docs.astral.sh/uv/getting-started/installation/).

## Local Workspace

The default user workspace is:

| Platform | Location               |
| -------- | ---------------------- |
| Windows  | `C:\Repos\tidy-gmail\` |
| macOS    | `~/Repos/tidy-gmail/`  |

The capitalization of `Repos` is intentional and consistent
across platforms.
Create this location if it does not exist.
The data/ is required.

```text
tidy-gmail/
├── data/
│   ├── config.toml
│   ├── senders_protected.csv
│   ├── senders_always_delete.csv (optional)
│   └── sender_decisions.csv
├── output/
│   ├── sender_summary.csv
│   ├── candidates.csv
│   └── cleanup_log.csv
└── .local/
    ├── credentials.json
    └── token.json
```

The workspace is independent of the installed Python package.

For developers, this directory may also be the local
Git checkout.
Folders containing personal configuration, credentials, state,
and reports must be excluded from Git.

Use `--workspace PATH` before any command to select an existing workspace.
For local development:

```shell
uv run tidy-gmail --workspace "C:\Repos\analytics-toolworks\tidy-gmail" doctor
```

See [Local privacy](docs/privacy.md) for Git checks, local permissions,
and recovery backups, and [Workflow](docs/index.md) for protection settings.

## Configuration

Configuration is maintained in `data/`.

- `config.toml` defines operational and protection settings.
- `senders_protected.csv` identifies known protected senders.
- Optional `senders_always_delete.csv` records permanent cleanup approvals.
- `sender_decisions.csv` records user decisions about senders.

Sender decisions are persistent and reusable across scans.

The application must not overwrite existing configuration
during initialization or upgrades.

## Classification and Protection

Messages are evaluated using rules.
The decision order is:

1. Protected messages are excluded from cleanup.
2. Explicitly approved senders may produce cleanup candidates.
3. Additional message-level protection rules are applied.
4. Unknown or ambiguous messages remain untouched.
5. Only eligible candidates enter a proposed cleanup batch.

Protection may include:

- Personal correspondence and self-addressed notes.
- Financial, tax, and legal records.
- Charitable contribution acknowledgments and receipts.
- Research correspondence and historical archives.
- Starred or important messages.
- Messages containing attachments, when configured.

For example, Gmail's Promotions category is a source of candidates,
not authorization to delete its contents.

### Permanent Sender Approvals

Use optional `data/senders_always_delete.csv` for ongoing sender approvals.
The file is loaded from the selected workspace, using trimmed,
case-insensitive email addresses rather than display names.
Start with this header and add only senders you have reviewed:

```csv
email,reason
newsletter@example.org,disposable newsletter
```

Membership satisfies `require_approved_sender = true` without an individual
`trash` decision. It does not authorize immediate deletion:
messages must be older than `cleanup.minimum_age_days` and pass every
existing protection. Recent messages are retained. Missing or invalid
dates are skipped, including during the final check before Trash.
Messages exactly at the age boundary are conservatively retained.

Protected senders, receipts and order confirmations, protected labels,
starred and important messages, attachment exclusions, sent-by-me
protection, category and Inbox rules, and other safeguards still apply.
Explicit `keep` or `review` decisions block permanent approval as conflicts.
Resolve conflicts yourself; the application never rewrites those decisions.

A missing permanent list means no permanent approvals; malformed existing
files stop validation. Duplicate normalized addresses are rejected.
The list is indexed once per command for fast membership checks.
Scanning never adds senders to this list. `init` creates a header-only
file if missing and preserves existing contents.
Existing private files are not migrated or rewritten by an upgrade.

Reports distinguish `[protected: reason]`, `[permanently approved; eligible: N]`,
`[individually approved; eligible: N]`, and `[undecided]`.
Receipt counts remain separate. Sender summaries retain individual decisions
and add approval source and reason columns.
`output/sender_conflicts.csv` lists every permanent approval conflict,
including senders outside the scanned inventory.

Cleanup remains an explicit command: permanent approval does not schedule
background work or bypass dry-run, `--execute`, or batch confirmation.
After confirmation, current Gmail search exclusions and message metadata,
including age, are checked again before each Trash operation.
Rules are loaded at command start; restart after editing approval files.
Gmail search, metadata retrieval, and Trash remain separate API operations.

### Protected Sender Reports

The selected workspace's `data/senders_protected.csv` controls sender
protection. Addresses are matched after trimming whitespace and ignoring case.
Protection overrides any `trash` sender decision and is checked again
immediately before each Trash request, independently of receipt detection.
Rules are loaded when the command starts; restart the command after editing them.

Reports display `[protected: reason]`, or `[protected]` for a blank reason,
in preference to a sender decision. Unprotected senders with eligible messages
show an approval source and eligible count; senders without a decision show `[undecided]`.
Undecided messages are not eligible for cleanup.
The sender summary preserves the saved decision and adds `protection_reason`.
The protected-message report also includes protected senders.

### Receipt Protection

Transactional records are protected before sender approval is considered.
Receipt protection applies across Gmail categories, including Updates,
and independently of Inbox membership, age, and dry-run mode.
An approved sender can have eligible promotional messages while its
receipts remain protected.

```toml
[protection]
protect_receipts = true
```

This setting defaults to `true` in older configurations.
Permanent protection cannot be disabled: `false` is a configuration error.
Existing sender, label, starred, important, attachment, and other
protections continue to apply.

Detection decodes Subject headers, normalizes case and punctuation,
and checks bounded patterns for receipts, invoices, orders, payments,
statements, transactions, and shipping confirmations.
It reads no message bodies and uses no additional Gmail permissions.
Missing or uninterpretable required metadata prevents cleanup.

`report` writes `output/protected_messages.csv` with protection reasons.
The sender summary includes separate receipt-protected and eligible counts.
Reports describe the scanned inventory, not the entire mailbox.
`candidates` excludes protected records.
After confirmation, cleanup fetches current metadata and reapplies
protection immediately before each Trash request. Skips include a reason.

Subject detection is conservative and may preserve some promotions.
It cannot reliably recognize vague subjects such as "Thank you",
body-only receipts, or every language and vendor-specific format.
Add sensitive senders to `data/senders_protected.csv` and protect Gmail
label IDs through `protection.label_ids` for additional coverage.
Gmail metadata retrieval and Trash are separate requests; Gmail provides
no atomic check-and-Trash guarantee in this workflow.

## Safety and Recovery

The intended default is **dry-run** mode.

Mailbox modification requires explicit authorization and
confirmation of the proposed batch.

Cleanup moves messages to Gmail Trash.
The application does not perform permanent deletion.

Every cleanup operation must generate an audit record
containing sufficient information to identify the affected
messages and support restoration.

Gmail's Trash is temporary.
The user should not rely on its retention period as the only backup.

Google OAuth credentials and authorization tokens are
stored locally and not be committed to Git.

## Development

The project uses:

- Python with a `src/` package layout.
- `uv` for dependency management.
- `uvx` for the published command-line application.
- Ruff for formatting and linting.
- ty for static type checking.
- pytest for automated tests.
- Zensical for documentation.

Tests must not access or modify a real Gmail account.
Gmail operations should be tested through controlled
fixtures and simulated API responses.

## Scope

This application is limited to Gmail.
The user is responsible for their own mailbox,
configuration, credentials, and cleanup decisions.

## Contributing

See [Development](docs/development.md) for checkout setup, local commands,
privacy checks, and validation. Release instructions are in
[CHANGELOG.md](CHANGELOG.md#release-procedure-required).

## Annotations

[.annotations/annotations.md](https://github.com/analytics-toolworks/tidy-gmail/blob/main/.annotations/annotations.md)

## Citation

[CITATION.cff](https://github.com/analytics-toolworks/tidy-gmail/blob/main/CITATION.cff)

## Documentation

- [Documentation](https://analytics-toolworks.github.io/tidy-gmail)

## License

[MIT](https://github.com/analytics-toolworks/tidy-gmail/blob/main/LICENSE)
