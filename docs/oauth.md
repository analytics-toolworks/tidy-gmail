# Gmail Authorization

Gmail access requires your own Google Cloud OAuth client.
Local configuration validation does not test this connection.

## 1. Create a Google Cloud Project

1. Follow the instructions to
   [Create a Google Cloud Project](https://developers.google.com/workspace/guides/create-project) (or use an existing one).
2. I used `tidy-gmail-gcloud-project` for the name and nothing for the organization.
3. Click Create.

## 2. Create a Google Cloud Project

Follow the setup sections in Google's
[Gmail Python quickstart](https://developers.google.com/workspace/gmail/api/quickstart/python).

### 2A. Enable the API

1. Go to  [Google Cloud](https://cloud.google.com).
2. Click "Console".
3. You may see the project you just created, if not select it.
4. Using the Python Quickstart instructions, click Enable the Gmail API.

### 2B. Configure the OAuth consent screen

1. Click Go to Branding.
2. Click Get Started.
3. App name = tidy-gmail
4. User support email  = your gmail (you are the only user of your app).
5. Click Next.
6. Audience = External.
7. Click Next.
8. Contact information = your gmail.
9. Click Next.
10. Finish: Read and check the box.
11. Click Continue.
12. Click Create.

OAuth audience: Select External, even if you are the only user.
Add your Gmail address as a test user while testing.
For continued personal use,
consider switching the publishing status to
In production because Testing-mode Gmail refresh tokens
expire after seven days.
Google provides a verification exception for personal-use applications.
Each tidy-gmail user creates and manages their own OAuth client;
no shared developer credentials are required.

### 2C. Authorize credentials for a desktop application

1. In the Python Quickstart, click "Go to Clients".
2. Click + Create Client.
3. Application type = Desktop app.
4. For Name, type a name for the credential.
   I used `tidy-gmail Local Desktop OAuth Client`.
5. Leave the AI-powered agent box **unchecked**.
6. Click Create.
7. IMPORTANT: Click Download JSON.
8. Save the downloaded JSON file as credentials.json
   in your tidy-gmail/.local directory, e.g., `C:\Repos\analytics-toolworks\tidy-gmail\.local\credentials.json`.
9. Click OK.

Use tidy-gmail's commands below instead of the quickstart's sample script.

## 3. Store Credentials Locally

Save the downloaded JSON as `.local/credentials.json` in your workspace.
Keep it out of Git and shared archives.
Follow [Local privacy](privacy.md) to restrict access.
Do not manually create `token.json`.

## 4. Add yourself as a test user

1. Open [Google Cloud / Google Auth Platform / Audience](https://console.cloud.google.com/auth/audience).
2. Ensure your tidy-gmail-gcloud-project project is selected
   and select if necessary.
3. Under Test users, click + Add users.
4. Enter your gmail.
5. Click Save.

## 5. Authorize and Scan

Published-package users run:

```shell
uvx tidy-gmail scan --limit 100
```

Developers using this checkout run:

```powershell
uv run tidy-gmail --workspace "C:\Repos\analytics-toolworks\tidy-gmail" scan --limit 100
```

The authorization flow opens a browser when needed.
Choose the Gmail account intended for this workspace.
Click Continue on the unverified screen.

Successful will show: The authentication flow has completed. You may close this window.

The application requests `gmail.modify` for inspection and later
Trash/restoration operations.
Scanning itself does not modify Gmail.
Successful authorization saves `.local/token.json`
for subsequent commands.

After scanning, run `report`,
review sender decisions,
and run `candidates`,
using the same command prefix and workspace.

Keep one Gmail account per workspace.

## Receipt Protection After Authorization

Receipt protection uses decoded Subject metadata from the existing
`gmail.modify` authorization. No new permission or reauthorization is
required for this feature. Scanning remains read-only for Gmail.
See [Receipt protection](index.md#receipt-protection) before cleanup.
