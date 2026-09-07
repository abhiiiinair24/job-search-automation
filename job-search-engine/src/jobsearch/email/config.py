"""Email delivery configuration.

The recipient (and any other delivery detail) comes entirely from
environment variables — never hard-coded in source, so this file is safe
to commit regardless of who's inbox the reports go to.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


class EmailConfigError(Exception):
    """Raised when required email-delivery environment variables are missing."""


@dataclass
class EmailConfig:
    recipient_email: str
    # Optional "From" header override. Gmail's API sends as the
    # authenticated account regardless, but this can select a verified
    # alias on that account, or otherwise is left as Gmail's default.
    sender_email: Optional[str] = None
    subject_prefix: str = ""

    @classmethod
    def from_env(cls) -> "EmailConfig":
        recipient = os.environ.get("JOBSEARCH_RECIPIENT_EMAIL")
        if not recipient:
            raise EmailConfigError(
                "JOBSEARCH_RECIPIENT_EMAIL is not set. The recipient must come from "
                "configuration/environment variables, not be hard-coded - set this "
                "env var (or the corresponding GitHub Actions secret) before sending."
            )
        return cls(
            recipient_email=recipient,
            sender_email=os.environ.get("JOBSEARCH_SENDER_EMAIL") or None,
            subject_prefix=os.environ.get("JOBSEARCH_EMAIL_SUBJECT_PREFIX", ""),
        )
