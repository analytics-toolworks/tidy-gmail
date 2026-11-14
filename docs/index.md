# tidy-gmail

<img
src="https://raw.githubusercontent.com/analytics-toolworks/tidy-gmail/main/docs/images/profile.png"
alt="profile logo"
width="110">

`tidy-gmail` is a local, data-driven Gmail cleanup application.
It separates inspection, protection rules, review, and mailbox changes.

## Design

- Preserve unknown messages and protected records.
- Require explicit sender approval before cleanup.
- Preview changes before moving messages to Trash.
- Record requests before Gmail operations and results afterward.
- Keep configuration, credentials, and reports local.

## Workflow

Use the same workspace for every command.
The default is `C:\Repos\tidy-gmail` on Windows
and `~/Repos/tidy-gmail` on macOS.

```shell
uvx tidy-gmail init
uvx tidy-gmail doctor
uvx tidy-gmail scan
uvx tidy-gmail report
uvx tidy-gmail candidates
```

For a custom location, pass `--workspace PATH` before every command.
For a source checkout, follow [Development](development.md).
Initialization preserves existing files.
Place your desktop OAuth client in `.local/credentials.json`.
Scanning initiates authorization when needed and fetches metadata, not bodies.
The current scan covers old messages in the configured Inbox categories,
not the whole mailbox.

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

## Protection

All protections take precedence over sender approval.
Start with trusted senders and labels, then add subject terms.

1. Add personal contacts, financial institutions, charities, and research
   correspondents to `data/senders_protected.csv`.
2. Add Gmail label IDs to `protection.label_ids` for records and archives.
   Use IDs such as `Label_123`, not display names.
3. Add your email address and aliases to `protection.own_addresses`.
4. Extend `protection.subject_contains` for legal, tax, donation,
   membership, and research records.
5. Keep starred, important, attachment, and sent-message protection enabled.

New optional settings default to empty lists for existing configurations.
Subject matching is case-insensitive substring matching;
it is conservative and cannot identify every valuable message.
Gmail attachment and self-sender search filters are checked live before Trash.

A candidate must have an approved `trash` sender decision or permanent approval,
match a configured category, exceed the minimum age,
remain in Inbox, and include a List-Unsubscribe header.
The header is evidence of a mailing list, not permission by itself.

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

## Cleanup and Recovery

Review `output/candidates.csv` and your sender decisions.
`trash` defaults to a preview.
Execution requires `cleanup.dry_run = false`, `--execute`,
and typing the displayed `TRASH N` confirmation.
Gmail eligibility is rechecked before confirmation.
The current interface selects up to `--limit` eligible messages;
it does not implement persisted batch IDs.

```shell
uvx tidy-gmail trash --limit 10
uvx tidy-gmail trash --limit 10 --execute
uvx tidy-gmail restore --limit 10
uvx tidy-gmail restore --limit 10 --execute
```

Supply `--workspace` before the command when using a custom location.
Restore requires `cleanup.dry_run = false`, `--execute`,
and its own `RESTORE N` confirmation.
It removes Trash and repairs original Inbox membership.
Interrupted restoration can be retried using the audit log.
It does not reconstruct every label or recover permanently deleted mail.

Run one modifying command at a time, keep the same Gmail account
for a workspace, and preserve `output/cleanup_log.csv`.
Do not switch authorization files between accounts in one workspace.

## See Also

- [Local privacy](./privacy.md)
- [OAuth setup](./oauth.md)
- [Development](./development.md)
- [API](./api.md)
