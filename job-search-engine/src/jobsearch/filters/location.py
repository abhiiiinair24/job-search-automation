"""US-location filtering (including 'Remote' postings)."""
from __future__ import annotations

import re

from jobsearch.models import Job

_US_STATE_ABBREVIATIONS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}

_US_SIGNAL_RE = re.compile(r"\b(usa|u\.s\.a?\.?|united states)\b", re.IGNORECASE)
_NON_US_SIGNAL_RE = re.compile(
    r"\b(india|canada|u\.?k\.?|united kingdom|europe|emea|apac|"
    r"toronto|london|bangalore|hyderabad|singapore|germany|australia|"
    r"mexico|philippines|poland|ireland(?!\s*,?\s*(?:oh|ny))|latam)\b",
    re.IGNORECASE,
)


def is_us_based(job: Job) -> bool:
    """Heuristic: True if the location string points to the US or plain 'Remote'.

    Excludes postings whose location clearly names a non-US country/region.
    A bare "Remote" with no country qualifier is treated as acceptable per
    the requirement that "Remote US is acceptable," since we have no
    negative signal to exclude it on.
    """
    location = job.location or ""

    if _NON_US_SIGNAL_RE.search(location):
        return False

    if _US_SIGNAL_RE.search(location):
        return True

    tokens = re.split(r"[,/]", location)
    for token in tokens:
        token = token.strip().upper()
        if token in _US_STATE_ABBREVIATIONS:
            return True

    if location.strip().lower() in {
        "remote", "remote - us", "remote (us)", "remote, us", "remote us",
    }:
        return True

    return False
