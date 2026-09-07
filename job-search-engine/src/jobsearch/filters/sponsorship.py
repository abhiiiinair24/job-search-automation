"""Heuristic visa-sponsorship detection from job description text.

This only catches postings that explicitly discuss sponsorship one way or
the other. Most postings say nothing about it at all, which is reported as
UNKNOWN rather than assumed to be favorable or unfavorable — that's the
default whenever the text doesn't give us a clear signal.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from jobsearch.models import Job, SponsorshipStatus

# Optional qualifier before the word "sponsorship" — covers "visa
# sponsorship", "immigration sponsorship", "H-1B sponsorship", or just
# bare "sponsorship".
_Q = r"(?:visa\s+|immigration\s+|h-?1b\s+)?"

_NOT_AVAILABLE_PATTERNS = [
    rf"(?:no|not|without)\s+{_Q}sponsorship",
    rf"(?:do|does)\s+not\s+(?:offer|provide)\s+{_Q}sponsorship",
    rf"(?:unable|not able) to (?:sponsor|provide {_Q}sponsorship)",
    rf"(?:cannot|can't|can not) (?:sponsor|provide {_Q}sponsorship)",
    r"(?:will|do|does) not sponsor",
    rf"{_Q}sponsorship (?:is |will be )?not (?:available|provided|offered)",
    rf"not eligible for {_Q}sponsorship",
    rf"no longer (?:sponsor|provide {_Q}sponsorship)",
]

_AVAILABLE_PATTERNS = [
    rf"{_Q}sponsorship(?:\s+is)?\s+available",
    rf"we (?:sponsor|offer|provide) {_Q}sponsorship",
    r"open to sponsor(?:ing)?",
    r"will sponsor",
]

_NOT_AVAILABLE_RE = re.compile("|".join(_NOT_AVAILABLE_PATTERNS), re.IGNORECASE)
_AVAILABLE_RE = re.compile("|".join(_AVAILABLE_PATTERNS), re.IGNORECASE)


def detect_sponsorship(text: str) -> Tuple[SponsorshipStatus, Optional[str]]:
    """Return a best-effort sponsorship status plus the matched evidence text.

    NOT_AVAILABLE is checked first: a posting that says both "we generally
    sponsor" and "not eligible for sponsorship in this specific case" should
    surface the more restrictive signal for a candidate deciding whether to
    apply.
    """
    if not text:
        return SponsorshipStatus.UNKNOWN, None

    not_available_match = _NOT_AVAILABLE_RE.search(text)
    if not_available_match:
        return SponsorshipStatus.NOT_AVAILABLE, not_available_match.group(0)

    available_match = _AVAILABLE_RE.search(text)
    if available_match:
        return SponsorshipStatus.AVAILABLE, available_match.group(0)

    return SponsorshipStatus.UNKNOWN, None


def annotate_sponsorship(job: Job) -> Job:
    """Fill in job.sponsorship_status / sponsorship_evidence, in place."""
    status, evidence = detect_sponsorship(job.description)
    job.sponsorship_status = status
    job.sponsorship_evidence = evidence
    return job
