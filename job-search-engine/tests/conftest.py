from datetime import datetime, timezone
from typing import Optional

import pytest

from jobsearch.models import Job, SourceType


@pytest.fixture
def make_job():
    """Factory fixture for building Job objects with sensible defaults in tests."""

    def _make(
        title: str = "Software Engineer",
        company: str = "Acme",
        location: str = "Remote - US",
        description: str = "",
        source: SourceType = SourceType.GREENHOUSE,
        source_job_id: str = "123",
        url: str = "https://example.com/job/123",
        date_updated: Optional[datetime] = None,
    ) -> Job:
        return Job(
            source=source,
            source_job_id=source_job_id,
            company=company,
            title=title,
            location=location,
            url=url,
            description=description,
            date_posted=date_updated,
            date_updated=date_updated or datetime.now(timezone.utc),
        )

    return _make
