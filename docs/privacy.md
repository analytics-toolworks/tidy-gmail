# Local Privacy and Recovery

Private mailbox files need separate protection from publication,
local access, and accidental deletion.

## Keep Private Files Out of Git

The repository ignores `/data/`, `/output/`, and `/.local/`.
Git ignores untracked files; ignore rules do not remove tracked files.
See the [Git documentation](https://git-scm.com/docs/gitignore).

Before publishing, run from the repository root:

```powershell
git check-ignore -v -- data/config.toml data/senders_protected.csv output/cleanup_log.csv .local/credentials.json .local/token.json

git ls-files -- data/ output/ .local/
```

The second command must return no paths.
Do not force-add private files.
Review GitHub Desktop's staged changes before committing.

## Restrict Local Access

Ignore rules do not restrict applications or Windows accounts.
On Windows, open `.local` Properties, Security, Advanced.
Disable inherited permissions by converting them to explicit entries.
Retain your own account, SYSTEM, and Administrators;
remove broad Users and Authenticated Users entries.
Apply the intended restrictions to existing files and subfolders,
then verify that your account can still use the directory.
Apply equivalent protection to `data` and `output` if they contain private mail data.

Applications running as your account can still read your files.
Use a trusted computer and protect its login and disk encryption.
Never include tokens in screenshots, support requests, or shared archives.

## Preserve Recovery Data

Keep private backups of sender decisions and cleanup logs.
Use encrypted backup storage with restricted access.
Credentials can be reauthorized; lost decisions and recovery records
cannot necessarily be recreated.

`sit.ps1` previews cleanup rather than automatically deleting detected files.
Review a cleanup plan before opting into deletion.
The inspected cached pup-clean implementation also discovers generated
files from source code; its fixed directory list alone is insufficient
proof that mailbox reports are preserved.
Do not run `git clean -fdx` in a workspace containing private data.

## Verify Before Connecting Gmail

Tests use temporary workspaces and simulated Gmail operations.
They never authorize a real mailbox.
Dry-run is the default, and Trash execution requires explicit confirmation.
The audit log records intent before the API request so interrupted
operations remain available for recovery.
