"""One-time local script to obtain a Gmail OAuth2 refresh token.

Run this ONCE, locally, with a browser available - NOT in CI/GitHub
Actions. It walks you through Google's OAuth consent screen for the
'gmail.send' scope (send-only - it can never read your inbox) and prints
a refresh token to store as a secret.

This script is NOT part of the jobsearch package and has no test coverage
of its own (it's an interactive, one-time bootstrapping tool, not
production code). It requires a separate package not otherwise needed by
jobsearch itself:

    pip install google-auth-oauthlib

Setup before running this:
    1. Create/select a project in Google Cloud Console.
    2. Enable the Gmail API for that project.
    3. Configure the OAuth consent screen (External is fine for personal
       use; add your own Google account as a test user).
    4. Create OAuth 2.0 credentials of type "Desktop app" - this gives you
       a client ID and client secret.

Usage:
    python scripts/get_gmail_refresh_token.py <client_id> <client_secret>

The script opens a browser for you to approve access, then prints the
three values to store as secrets (locally in .env for testing, later as
GitHub Actions repository secrets). Nothing is written to disk by this
script - copy the printed values yourself.
"""
from __future__ import annotations

import sys

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python get_gmail_refresh_token.py <client_id> <client_secret>")
        return 1

    client_id, client_secret = sys.argv[1], sys.argv[2]

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("This one-time script needs google-auth-oauthlib:")
        print("    pip install google-auth-oauthlib")
        return 1

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    credentials = flow.run_local_server(port=0)

    if not credentials.refresh_token:
        print(
            "\nNo refresh token was returned. This usually means you've already "
            "authorized this app before and Google didn't re-issue one. Go to "
            "https://myaccount.google.com/permissions, revoke access for this "
            "app, and run this script again."
        )
        return 1

    print("\nSuccess! Store these as secrets - never commit them:\n")
    print(f"GMAIL_CLIENT_ID={client_id}")
    print(f"GMAIL_CLIENT_SECRET={client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={credentials.refresh_token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
