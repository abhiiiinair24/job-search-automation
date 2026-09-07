"""Gmail sending via the Gmail API (not SMTP).

Kept separate from credential loading (gmail_auth.py) and email content
formatting (formatter.py) so that:

- formatter.py can be tested with zero mocking (pure functions).
- gmail_auth.py's config validation can be tested without any Google
  library installed/mocked.
- Only this module needs its network calls mocked in tests.

Nothing in this module marks jobs as seen — send_search_result_email()
sends the email and returns the Gmail API's response; it is the caller's
(future orchestration layer's) job to decide, after confirming a
successful send, whether/when to call a SeenJobStore.mark_seen(...).
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime
from email.mime.text import MIMEText
from typing import Optional

from jobsearch.email.config import EmailConfig
from jobsearch.email.formatter import format_email_subject, format_search_result_email
from jobsearch.email.gmail_auth import GmailAuthConfig, build_credentials
from jobsearch.engine import SearchResult

logger = logging.getLogger(__name__)


class GmailSendError(Exception):
    """Raised when the Gmail API reports a failure sending the message."""


def build_raw_message(
    to_address: str,
    subject: str,
    html_body: str,
    from_address: Optional[str] = None,
) -> str:
    """Build the base64url-encoded RFC 2822 message the Gmail API's `raw` field expects."""
    message = MIMEText(html_body, "html", "utf-8")
    message["to"] = to_address
    message["subject"] = subject
    if from_address:
        message["from"] = from_address
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")


def send_email(
    to_address: str,
    subject: str,
    html_body: str,
    from_address: Optional[str] = None,
    auth_config: Optional[GmailAuthConfig] = None,
) -> dict:
    """Send an HTML email via the Gmail API. Returns the API response dict.

    Raises GmailSendError on any failure. The googleapiclient import is
    deliberately local to this function so other parts of this package
    (and callers who only need formatting) don't require it to be
    importable unless they actually try to send.
    """
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    credentials = build_credentials(auth_config)
    raw = build_raw_message(to_address, subject, html_body, from_address)

    try:
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        response = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except HttpError as exc:
        raise GmailSendError(f"Gmail API send failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - surface any transport/auth failure uniformly
        raise GmailSendError(f"Unexpected error sending email via Gmail API: {exc}") from exc

    logger.info("Email sent via Gmail API (message id=%s)", response.get("id"))
    return response


def send_search_result_email(
    result: SearchResult,
    email_config: Optional[EmailConfig] = None,
    auth_config: Optional[GmailAuthConfig] = None,
    candidate_years: Optional[float] = None,
    generated_at: Optional[datetime] = None,
) -> dict:
    """Format a SearchResult and send it via Gmail in one step.

    Convenience wrapper composing formatter.py + this module's send_email;
    it still does nothing beyond formatting and sending — no seen-store
    interaction happens here (see module docstring).
    """
    email_config = email_config or EmailConfig.from_env()

    subject = format_email_subject(result)
    if email_config.subject_prefix:
        subject = f"{email_config.subject_prefix}{subject}"

    html_body = format_search_result_email(
        result, generated_at=generated_at, candidate_years=candidate_years
    )

    return send_email(
        to_address=email_config.recipient_email,
        subject=subject,
        html_body=html_body,
        from_address=email_config.sender_email,
        auth_config=auth_config,
    )
