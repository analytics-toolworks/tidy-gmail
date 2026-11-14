# Changelog

<!-- markdownlint-disable MD024 -->

All notable changes to this project will be documented in this file.

The format is based on **[Keep a Changelog](https://keepachangelog.com/en/1.1.0/)**
and this project adheres to **[Semantic Versioning](https://semver.org/spec/v2.0.0.html)**.

---

## [Unreleased]

### Added

- Automatic resumption of bounded Gmail scans across invocations.
- Private SQLite checkpoints that commit metadata and cursor progress together.
- Explicit scan restart with private archives of earlier results.
- Partial/complete scan status and unavailable-message reports.
- Query and account identity checks, bounded read retries, and invalid-token diagnostics.
- Synthetic pagination, Ctrl+C, process-crash, deduplication, and large-inventory tests.

### Changed

- Scan inventory now accumulates unique records instead of replacing prior batches.
- Reports can read committed scan metadata even after interrupted CSV export.
- Sender discovery writes additions atomically while preserving existing decisions.

### Added

- Optional permanent sender approvals in `data/senders_always_delete.csv`.
- Approval source reporting and explicit keep/review conflict reports.
- Synthetic coverage for large lists, age boundaries, and final safety checks.

### Changed

- Refresh Gmail search exclusions before every Trash request.
- Apply configured dry-run to CLI restoration as well as cleanup.

### Fixed

- Protected sender report labels now show protection reasons instead of
  undecided or trash decisions, while preserving saved sender decisions.
- Added synthetic regression coverage for workspace selection and protected
  senders at candidate selection and the final pre-Trash check.

### Changed

- Separated published-user instructions in the README from source-checkout
  and maintainer instructions in the development documentation.

### Added

- Permanent receipt protection with a default-enabled configuration setting.
- Decoded Subject matching for transactional records across Gmail categories.
- Receipt and invalid-metadata reports with separate sender summary counts.
- Final per-message metadata protection checks after cleanup confirmation.
- Offline tests for receipt formats, missing metadata, and changed candidates.

- CSV header examples and troubleshooting for preserved empty configuration.
- Explanation of successful local validation and the next OAuth setup step.

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
- Versions are driven by git tags. Tag `vX.Y.Z` to release.
- Docs are deployed per version tag and aliased to **latest**.

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

uvx

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
git tag -d vX.Z.Y
git push origin :refs/tags/vX.Z.Y
```

## Links

[Unreleased]: https://github.com/analytics-toolworks/tidy-gmail/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/analytics-toolworks/tidy-gmail/releases/tag/v0.1.0

<!-- markdownlint-enable MD024 -->
