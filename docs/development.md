# Development

These instructions are for contributors working in a source checkout.
The [README](https://github.com/analytics-toolworks/tidy-gmail/blob/main/README.md) describes the published user application.
The [changelog](https://github.com/analytics-toolworks/tidy-gmail/blob/main/CHANGELOG.md) records changes and release procedures.

## Run the Current Source

Use Python 3.15 and run commands from the repository root.
Install the locked dependencies with `uv sync --locked`.
`uv run tidy-gmail` runs this checkout; `uvx tidy-gmail` runs a published package.
Do not run `git init` again in an existing checkout.

For this Windows checkout:

```powershell
uv run tidy-gmail --workspace "C:\Repos\analytics-toolworks\tidy-gmail" init
uv run tidy-gmail --workspace "C:\Repos\analytics-toolworks\tidy-gmail" doctor
```

Use the same `--workspace` option before `scan`, `report`, `candidates`,
`trash`, or `restore`. A successful local check does not test OAuth.
Follow the README's protection and OAuth instructions before scanning.

## Resume a Local Scan

Use the same selected workspace for every invocation:

```powershell
uv run tidy-gmail --workspace "C:\Repos\analytics-toolworks\tidy-gmail" scan --limit 1000
uv run tidy-gmail --workspace "C:\Repos\analytics-toolworks\tidy-gmail" scan --limit 1000
```

The second command resumes automatically. Ctrl+C exits with status 130;
run the same command again to continue. To archive previous results and
intentionally start fresh:

```powershell
uv run tidy-gmail --workspace "C:\Repos\analytics-toolworks\tidy-gmail" scan --restart --limit 1000
```

See [Incremental scanning](index.md#incremental-and-resumable-scanning)
for checkpoint storage, partial reports, and invalid-token recovery.
No live Gmail account is needed for the synthetic pagination and crash tests.

## Protect a Checkout Used as a Workspace

Follow [Local privacy](privacy.md) before staging or publishing files.
`git check-ignore -v` should identify ignore rules for private paths.
`git ls-files -- data/ output/ .local/` must return no paths.
Empty output is the expected result, not an error.
GitHub Desktop may be used for reviewing and committing source changes.
Do not force-add private workspace files.

## Validate Changes

```shell
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run python -m pytest
uv run python -m zensical build
```

Tests use temporary workspaces and simulated Gmail responses.
They must not authorize or modify a real Gmail account.

## Maintainer Command Reference

### Clone and Open in VS Code

Open a machine terminal where you want the project:

```text
git clone https://github.com/analytics-toolworks/tidy-gmail

cd tidy-gmail
code .
```

### In a VS Code terminal

```shell
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

# save progress
git add -A
git commit -m "update"
git push -u origin main
```
