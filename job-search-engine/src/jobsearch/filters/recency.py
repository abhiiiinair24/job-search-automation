"""Recency filtering — keep only jobs posted/updated within a recent window."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from jobsearch.models import Job


def is_recent(
    job: Job,
    reference_time: Optional[datetime] = None,
    max_age_days: int = 4,
) -> bool:
    """True if the job's most recent known date is within max_age_days of reference_time.

    Jobs with no parseable date are excluded rather than assumed recent,
    since we can't verify the recency requirement for them.
    """
    reference_time = reference_time or datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    most_recent = job.most_recent_date
    if most_recent is None:
        return False
    if most_recent.tzinfo is None:
        most_recent = most_recent.replace(tzinfo=timezone.utc)

    return timedelta(0) <= reference_time - most_recent <= timedelta(days=max_age_days)
