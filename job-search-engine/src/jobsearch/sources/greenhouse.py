"""Greenhouse ATS job source, using the public job-board API.

Greenhouse job boards are public and keyed by a 'board token' — usually the
company's slug, e.g. https://boards.greenhouse.io/stripe -> board_token
= "stripe". No API key is required for this read-only endpoint.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from jobsearch.models import Job, SourceType
from jobsearch.sources.base import JobSource, JobSourceError

logger = logging.getLogger(__name__)

GREENHOUSE_API_BASE = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseJobSource(JobSource):
    """Fetches postings from a single company's Greenhouse job board."""

    def __init__(
        self,
        board_token: str,
        company_name: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        self.board_token = board_token
        self.company_name = company_name or board_token
        self.name = f"greenhouse:{board_token}"
        self.timeout = timeout

    def fetch_jobs(self) -> List[Job]:
        url = f"{GREENHOUSE_API_BASE}/{self.board_token}/jobs?content=true"
        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise JobSourceError(f"request to {url} failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise JobSourceError(f"invalid JSON from {url}: {exc}") from exc

        raw_jobs = payload.get("jobs", [])
        jobs: List[Job] = []
        for raw in raw_jobs:
            try:
                jobs.append(self._parse_job(raw))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping malformed Greenhouse job on board '%s': %s",
                    self.board_token,
                    exc,
                )
        return jobs

    def _parse_job(self, raw: Dict[str, Any]) -> Job:
        location = (raw.get("location") or {}).get("name", "") or ""
        content = raw.get("content", "") or ""
        updated_at = self._parse_datetime(raw.get("updated_at"))

        return Job(
            source=SourceType.GREENHOUSE,
            source_job_id=str(raw["id"]),
            company=self.company_name,
            title=(raw.get("title") or "").strip(),
            location=location.strip(),
            url=raw.get("absolute_url", "") or "",
            description=content,
            date_posted=updated_at,
            date_updated=updated_at,
            is_remote="remote" in location.lower(),
        )

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("Could not parse Greenhouse datetime '%s'", value)
            return None
