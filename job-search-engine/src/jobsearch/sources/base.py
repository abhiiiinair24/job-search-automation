"""Abstract base class for job sources."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List

from jobsearch.models import Job

logger = logging.getLogger(__name__)


class JobSourceError(Exception):
    """Raised when a job source fails to fetch or parse postings."""


class JobSource(ABC):
    """Common interface for anything that can produce a list of Job objects."""

    name: str = "base"

    @abstractmethod
    def fetch_jobs(self) -> List[Job]:
        """Fetch and normalize jobs from this source.

        Implementations should raise JobSourceError on failure; they should
        NOT let arbitrary/unexpected exceptions propagate uncaught, so
        callers can degrade gracefully when one source is broken.
        """
        raise NotImplementedError

    def safe_fetch_jobs(self) -> List[Job]:
        """Fetch jobs, catching and logging any error instead of raising.

        This is what orchestration code should call so that a single
        misbehaving or unreachable source doesn't take down an entire run.
        """
        try:
            return self.fetch_jobs()
        except JobSourceError as exc:
            logger.error("Job source '%s' failed: %s", self.name, exc)
        except Exception as exc:  # noqa: BLE001 - deliberate broad catch at the boundary
            logger.exception("Job source '%s' raised an unexpected error: %s", self.name, exc)
        return []
