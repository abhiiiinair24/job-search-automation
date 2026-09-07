"""Job deduplication using stable identifiers."""
from __future__ import annotations

from typing import Iterable, List, Set

from jobsearch.models import Job


def deduplicate_jobs(jobs: Iterable[Job]) -> List[Job]:
    """Drop duplicate postings, keeping the first occurrence of each stable_id.

    Stable IDs are source + native ATS id when available, falling back to a
    hash of normalized company/title/location (see Job.stable_id). This is
    also what should be persisted between runs to determine whether a job
    is new or already seen.
    """
    seen: Set[str] = set()
    deduped: List[Job] = []
    for job in jobs:
        key = job.stable_id
        if key in seen:
            continue
        seen.add(key)
        deduped.append(job)
    return deduped
