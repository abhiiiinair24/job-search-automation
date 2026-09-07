"""Gmail OAuth2 credential loading.

Designed for headless/CI use (e.g. GitHub Actions): credentials are loaded
entirely from environment variables / secrets, never from files. This
module builds a `google.oauth2.credentials.Credentials` object from a
long-lived refresh token; the short-lived access token is fetched/renewed
automatically by the google-auth library whenever a request needs one, so
nothing needs to be persisted between runs.

Getting a refresh token in the first place is a ONE-TIME, local, manual
step (browser-based OAuth consent) — this module does not perform that
interactive flow itself. See scripts/get_gmail_refresh_token.py and the
README for that one-time setup.

This module never reads or writes credentials.json / token.json / any
other credential file, and never logs secret values.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"

_REQUIRED_ENV_VARS = ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")


class GmailAuthConfigError(Exception):
    """Raised when required Gmail OAuth2 environment variables are missing."""


@dataclass
class GmailAuthConfig:
    client_id: str
    client_secret: str
    refresh_token: str
    token_uri: str = DEFAULT_TOKEN_URI

    @classmethod
    def from_env(cls) -> "GmailAuthConfig":
        values = {name: os.environ.get(name) for name in _REQUIRED_ENV_VARS}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise GmailAuthConfigError(
                "Missing required Gmail OAuth2 environment variable(s): "
                + ", ".join(missing)
                + ". These must be set (e.g. as GitHub Actions secrets) - see README."
            )

        return cls(
            client_id=values["GMAIL_CLIENT_ID"],
            client_secret=values["GMAIL_CLIENT_SECRET"],
            refresh_token=values["GMAIL_REFRESH_TOKEN"],
            token_uri=os.environ.get("GMAIL_TOKEN_URI", DEFAULT_TOKEN_URI),
        )


def build_credentials(config: Optional[GmailAuthConfig] = None):
    """Build a google.oauth2.credentials.Credentials from a GmailAuthConfig.

    The google-auth import is deliberately local to this function (rather
    than at module level) so that GmailAuthConfig and its from_env()
    validation can be imported and unit-tested without the google-auth
    package needing to be importable — only actually building/using
    credentials requires it.
    """
    from google.oauth2.credentials import Credentials

    config = config or GmailAuthConfig.from_env()
    return Credentials(
        token=None,  # no access token yet - will be fetched via the refresh grant
        refresh_token=config.refresh_token,
        token_uri=config.token_uri,
        client_id=config.client_id,
        client_secret=config.client_secret,
        scopes=[GMAIL_SEND_SCOPE],
    )
