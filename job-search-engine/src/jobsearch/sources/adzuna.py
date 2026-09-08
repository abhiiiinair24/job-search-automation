"""Adzuna job-search discovery source.

Unlike Greenhouse/Lever (which require already knowing a company), Adzuna
is a genuine keyword-based job search API: search by role, get back
whichever companies are actually hiring for it right now. This is the
PRIMARY discovery mechanism among the integrated sources - the only one
that finds companies the candidate never named.

Adzuna does NOT provide complete coverage of the US job market - it is
one aggregator among several, and coverage depends on what's fed into its
own index. Treat it as a broad, free, ToS-compliant sample, not an
exhaustive listing. "Personal research" is an explicitly permitted use
case in Adzuna's API Terms of Service, which is what this qualifies as.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import requests

from jobsearch.models import Job, SourceType
from jobsearch.sources.base import JobSource, JobSourceError
from jobsearch.sources.enrichment import enrich_jobs

logger = logging.getLogger(__name__)

ADZUNA_API_BASE = "https://api.adzuna.com/v1/api/jobs"


class AdzunaDiscoverySource(JobSource):
    """Searches Adzuna for each of a candidate's target roles, US-only.

    One query per search term (not per company) - this is what makes it
    "discovery" rather than a maintained list. A single term failing
    (network error, bad response) doesn't stop the others; fetch_jobs()
    only raises if every term failed to return anything at all.
    """

    def __init__(
        self,
        app_id: str,
        app_key: str,
        search_terms: List[str],
        country: str = "us",
        max_days_old: int = 4,
        results_per_page: int = 25,
        enrich: bool = True,
        enrichment_max_companies: int = 20,
        timeout: float = 15.0,
    ) -> None:
        self.app_id = app_id
        self.app_key = app_key
        self.search_terms = search_terms
        self.country = country
        self.max_days_old = max_days_old
        self.results_per_page = results_per_page
        self.enrich = enrich
        self.enrichment_max_companies = enrichment_max_companies
        self.timeout = timeout
        self.name = "adzuna"

    def fetch_jobs(self) -> List[Job]:
        if not self.search_terms:
            logger.warning("AdzunaDiscoverySource has no search terms configured; skipping.")
            return []

        seen_ids: Set[str] = set()
        jobs: List[Job] = []
        any_term_succeeded = False

        for term in self.search_terms:
            try:
                term_jobs = self._fetch_for_term(term)
                any_term_succeeded = True
            except JobSourceError as exc:
                logger.warning("Adzuna search for '%s' failed: %s", term, exc)
                continue

            for job in term_jobs:
                if job.source_job_id in seen_ids:
                    continue
                seen_ids.add(job.source_job_id)
                jobs.append(job)

        if not any_term_succeeded:
            raise JobSourceError("All Adzuna search terms failed - see warnings above.")

        if self.enrich and jobs:
            jobs = enrich_jobs(jobs, max_companies=self.enrichment_max_companies)

        return jobs

    def _fetch_for_term(self, term: str) -> List[Job]:
        url = f"{ADZUNA_API_BASE}/{self.country}/search/1"
        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "what": term,
            "max_days_old": self.max_days_old,
            "results_per_page": self.results_per_page,
            "content-type": "application/json",
        }
        try:
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise JobSourceError(f"request to Adzuna for '{term}' failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise JobSourceError(f"invalid JSON from Adzuna for '{term}': {exc}") from exc

        results = payload.get("results", [])
        jobs: List[Job] = []
        for raw in results:
            try:
                jobs.append(self._parse_job(raw))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping malformed Adzuna result for '%s': %s", term, exc)
        return jobs

    def _parse_job(self, raw: Dict[str, Any]) -> Job:
        company = (raw.get("company") or {}).get("display_name", "") or "Unknown"
        location = (raw.get("location") or {}).get("display_name", "") or ""
        created = self._parse_datetime(raw.get("created"))

        return Job(
            source=SourceType.ADZUNA,
            source_job_id=str(raw["id"]),
            company=company,
            title=(raw.get("title") or "").strip(),
            location=location.strip(),
            url=raw.get("redirect_url", "") or "",
            description=raw.get("description", "") or "",
            date_posted=created,
            date_updated=created,
            is_remote="remote" in location.lower(),
        )

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("Could not parse Adzuna datetime '%s'", value)
            return None
