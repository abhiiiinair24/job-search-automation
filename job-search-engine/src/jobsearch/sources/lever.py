"""Lever ATS job source, using the public postings API.

Lever postings are public under a company's slug, e.g.
https://jobs.lever.co/<slug>. No API key is required for this read-only
JSON endpoint.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from jobsearch.models import Job, SourceType
from jobsearch.sources.base import JobSource, JobSourceError

logger = logging.getLogger(__name__)

LEVER_API_BASE = "https://api.lever.co/v0/postings"


class LeverJobSource(JobSource):
    """Fetches postings from a single company's Lever postings API."""

    def __init__(
        self,
        company_slug: str,
        company_name: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        self.company_slug = company_slug
        self.company_name = company_name or company_slug
        self.name = f"lever:{company_slug}"
        self.timeout = timeout

    def fetch_jobs(self) -> List[Job]:
        url = f"{LEVER_API_BASE}/{self.company_slug}?mode=json"
        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise JobSourceError(f"request to {url} failed: {exc}") from exc

        try:
            raw_jobs = response.json()
        except ValueError as exc:
            raise JobSourceError(f"invalid JSON from {url}: {exc}") from exc

        if not isinstance(raw_jobs, list):
            raise JobSourceError(f"unexpected payload shape from {url}")

        jobs: List[Job] = []
        for raw in raw_jobs:
            try:
                jobs.append(self._parse_job(raw))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping malformed Lever job for '%s': %s", self.company_slug, exc
                )
        return jobs

    def _parse_job(self, raw: Dict[str, Any]) -> Job:
        categories = raw.get("categories", {}) or {}
        location = categories.get("location", "") or ""
        description = raw.get("descriptionPlain") or raw.get("description") or ""
        created_at = self._parse_epoch_ms(raw.get("createdAt"))

        return Job(
            source=SourceType.LEVER,
            source_job_id=str(raw.get("id", "")),
            company=self.company_name,
            title=(raw.get("text") or "").strip(),
            location=location.strip(),
            url=raw.get("hostedUrl") or raw.get("applyUrl") or "",
            description=description,
            date_posted=created_at,
            date_updated=created_at,
            is_remote="remote" in location.lower(),
        )

    @staticmethod
    def _parse_epoch_ms(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        except (ValueError, TypeError):
            logger.warning("Could not parse Lever epoch millis '%s'", value)
            return None
