"""Core data models for the job-search engine."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class SponsorshipStatus(str, Enum):
    """What we could determine about visa sponsorship for a posting."""

    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"
    UNKNOWN = "unknown"


class SourceType(str, Enum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"


@dataclass
class Job:
    """A single normalized job posting, regardless of which source it came from."""

    source: SourceType
    source_job_id: str  # stable id from the ATS (e.g. Greenhouse job id)
    company: str
    title: str
    location: str
    url: str
    description: str
    date_posted: Optional[datetime] = None
    date_updated: Optional[datetime] = None
    is_remote: bool = False
    raw_experience_text: Optional[str] = None
    min_experience_years: Optional[int] = None
    max_experience_years: Optional[int] = None
    # "overall" | "tech_specific" | "unspecified" | None (nothing parsed at all)
    experience_basis: Optional[str] = None
    experience_matched_tech: Optional[str] = None
    sponsorship_status: SponsorshipStatus = SponsorshipStatus.UNKNOWN
    sponsorship_evidence: Optional[str] = None
    fit_score: float = 0.0
    fit_explanation: str = ""
    matched_keywords: List[str] = field(default_factory=list)

    @property
    def stable_id(self) -> str:
        """Stable identifier used for deduplication and 'seen before' tracking.

        Prefers source + source-native job id, which is stable across runs.
        Falls back to a hash of normalized company/title/location when a
        source id isn't available, so postings without a native id can still
        be deduplicated (though less reliably, since text can shift slightly
        between fetches).
        """
        if self.source_job_id:
            return f"{self.source.value}:{self.source_job_id}"
        normalized = (
            f"{self.company.strip().lower()}|"
            f"{self.title.strip().lower()}|"
            f"{self.location.strip().lower()}"
        )
        return f"fallback:{hashlib.sha256(normalized.encode()).hexdigest()[:16]}"

    @property
    def most_recent_date(self) -> Optional[datetime]:
        """The best available signal for how recently this posting changed."""
        return self.date_updated or self.date_posted
