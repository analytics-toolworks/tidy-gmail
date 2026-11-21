# Changelog

<!-- markdownlint-disable MD024 -->

All notable changes to this project will be documented in this file.

The format is based on **[Keep a Changelog](https://keepachangelog.com/en/1.1.0/)**
and this project adheres to **[Semantic Versioning](https://semver.org/spec/v2.0.0.html)**.

---

## [Unreleased]

---

## [0.2.0] - 2026-11-21

### Added

- Resume bounded Gmail scans across runs. Private SQLite checkpoints save
  message metadata and scan progress together.
- Start a fresh scan with `scan --restart` and retain the previous scan
  in a private archive.
- Report whether scan coverage is partial or complete and identify messages
  whose metadata was unavailable.
- Check the Gmail account and query when resuming a scan. Retry bounded
  read operations and report invalid-token errors.
- Support standing sender approvals in `data/senders_always_delete.csv`.
  Reports identify the approval source and flag conflicting keep or review
  decisions.
- Protect receipts using decoded subject lines across Gmail categories.
  Report receipts and invalid metadata separately in sender summaries.
- Document CSV headers, troubleshooting for empty configuration files,
  and the OAuth setup step after local validation.
- Add offline tests for pagination, interrupted scans, deduplication,
  large inventories and sender lists, age boundaries, workspace selection,
  receipts, missing metadata, and final protection checks.

### Changed

- Accumulate unique messages across scan batches. Reports can read committed
  scan results even if CSV export was interrupted.
- Save newly discovered senders atomically while preserving existing decisions.
- Recheck Gmail search conditions and message metadata immediately before
  moving each confirmed message to Trash.
- Apply the configured dry-run setting to restoration as well as cleanup.
- Report the saved candidate count and the Trash batch limit separately.
- Keep published-user instructions in the README and source-checkout and
  maintainer instructions in the development documentation.

### Fixed

- Apply the Trash batch limit after checking live eligibility. Repeated
  `trash --execute` runs now skip messages already moved to Trash and
  continue through the saved candidates until the batch is full or the
  list is exhausted.
- Show the protection reason for protected senders in reports while
  preserving their saved decisions.

---

## [0.1.0] - 2026-11-14

### Added

- Local-first Gmail cleanup command-line application.
- `uvx tidy-gmail` entry point and configurable `--workspace` path.
- Windows and macOS workspace conventions.
- Workspace initialization that preserves existing configuration.
- Local configuration validation with `doctor`.
- Gmail OAuth authorization and metadata-only inspection.
- Persistent sender decisions and protected sender lists.
- Configurable protection for Gmail label IDs, own addresses,
  and subject keywords.
- Sender discovery, inventory, and cleanup candidate reports.
- Dry-run defaults, live eligibility checks, and explicit
  confirmation before moving messages to Gmail Trash.
- Durable audit logging and restoration of Inbox membership.
- Recovery support for interrupted restoration operations.
- Offline tests for classification, Gmail requests, cleanup,
  and recovery.
- Workflow and local privacy documentation.

### Changed

- Standardized the protected sender filename as
  `senders_protected.csv`.
- Separated authorization, inventory, classification, reporting,
  cleanup, and restoration into dedicated modules.
- Made packaged templates the source of starter configuration.

### Fixed

- Restoration retries after untrashing succeeds but restoring
  Inbox membership fails.
- Validation of an explicitly supplied zero cleanup limit.
- Stale documentation and lint errors.

---

## Notes on Versioning and Releases

- We use **SemVer**:
  - **MAJOR** - breaking changes
  - **MINOR** - backward-compatible
  - **PATCH** - fixes, documentation, tooling
- Versions are driven by git tags.
- Push `vX.Y.Z` to start the release workflow.
- Documentation deploys to GitHub Pages on pushes to `main`
  and can also be deployed manually.
- Each GitHub Release includes four attached assets:
  - Python wheel (`.whl`)
  - Source distribution (`.tar.gz`)
  - SPDX SBOM (`sbom.spdx.json`)
  - CycloneDX SBOM (`sbom.cdx.json`)
- PyPI receives the wheel and source distribution through Trusted Publishing.
  The publishing action generates and uploads a PEP 740 attestation for each
  distribution file by default.

## Release Procedure (Required)

Follow these steps exactly when creating a new release.

### Task 1. Update release metadata (manual edits)

1. Update `CITATION.cff`: change `version` and `date-released`
2. Update `CHANGELOG.md`: move from unreleased, add entry, update links
3. Update `pyproject.toml`: update `[tool.hatch.version] fallback-version`

### Task 2. Validate

```shell
.\sit.ps1

# OR

uv self update
uv python install
uv lock --upgrade
uv sync
uv audit

# set up and run git hooks
uvx prek install --force
uvx prek update

git add -A
uvx prek run --all-files
# repeat if changes were made
uvx prek run --all-files

# run common chores
uv run ruff format .
uv run ruff check . --fix
uv run ty check
uv run python -m pytest
uv run python -m zensical build

uv run python -c "import shutil; from pathlib import Path; shutil.rmtree(Path('dist'), ignore_errors=True)"

uv build
uvx twine check dist/*

# update .github/workflows
uvx gha-tools autoupdate --pin=all --write .github/workflows

# check
uvx zizmor@latest .github/ --fix
# 1 informational or suppressed are still okay
```

### Task 3. Commit, push, tag

```shell
git add -A
git commit -m "Prepare X.Y.Z"
git push -u origin main
```

Verify actions run on GitHub. After success:

```shell
git tag vX.Y.Z -m "X.Y.Z"
git push origin vX.Y.Z
```

## Only As Needed (delete a tag)

```shell
git tag -d vX.Y.Z
git push origin :refs/tags/vX.Y.Z
```

## Links

[Unreleased]: https://github.com/analytics-toolworks/tidy-gmail/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/analytics-toolworks/tidy-gmail/releases/tag/v0.2.0
[0.1.0]: https://github.com/analytics-toolworks/tidy-gmail/releases/tag/v0.1.0

<!-- markdownlint-enable MD024 -->
