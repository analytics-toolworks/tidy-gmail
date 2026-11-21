"""Gmail OAuth authorization and local credential management."""

import os
from pathlib import Path
import tempfile
from typing import Any

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def connect(root: Path) -> Any:
    """Authorize the user's own desktop OAuth client, stored locally."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    secret = root / ".local" / "credentials.json"
    token = root / ".local" / "token.json"

    if not secret.is_file():
        raise FileNotFoundError(
            f"Missing {secret}. Create a Google Cloud Desktop OAuth "
            "client with Gmail API enabled and save its JSON here."
        )

    credentials = None

    if token.is_file():
        credentials = Credentials.from_authorized_user_file(
            str(token),
            SCOPES,
        )

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            credentials = InstalledAppFlow.from_client_secrets_file(
                str(secret),
                SCOPES,
            ).run_local_server(port=0)

        # WHY: Create private temporary storage before writing token contents.
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=token.parent,
                prefix=".token-",
                suffix=".tmp",
                encoding="utf-8",
                delete=False,
            ) as stream:
                temporary = stream.name
                stream.write(credentials.to_json())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, token)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    return build(
        "gmail",
        "v1",
        credentials=credentials,
        cache_discovery=False,
    )
