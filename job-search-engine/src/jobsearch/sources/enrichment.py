"""Best-effort Greenhouse/Lever enrichment for Adzuna-discovered jobs.

Adzuna's own listing gives a redirect URL and a truncated description.
When the hiring company also happens to run a public Greenhouse or Lever
board, this module tries to find the matching posting there and swap in
its cleaner direct URL and full description - but only when a confident
title match is found. This is a real, verifiable HTTP lookup (never an
assumption about a company's ATS), and it degrades gracefully: a company
whose board can't be guessed, or where no posting title matches
confidently enough, is left exactly as Adzuna reported it. A job is never
dropped because enrichment failed or was skipped.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from jobsearch.models import Job
from jobsearch.sources.base import JobSourceError
from jobsearch.sources.greenhouse import GreenhouseJobSource
from jobsearch.sources.lever import LeverJobSource

logger = logging.getLogger(__name__)

_LEGAL_SUFFIX_RE = re.compile(
    r",?\s+(inc\.?|llc\.?|ltd\.?|corp\.?|corporation|co\.?|company|limited)\s*$",
    re.IGNORECASE,
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def slug_candidates(company_name: str) -> List[str]:
    """Generate a small set of plausible Greenhouse/Lever slug guesses.

    Heuristic, not guaranteed - e.g. "Notion Labs, Inc." -> ["notion",
    "notionlabs", "notion-labs"]. Order reflects which guess is most
    likely correct; callers try them in order and stop at the first hit.
    """
    if not company_name:
        return []

    cleaned = _LEGAL_SUFFIX_RE.sub("", company_name.strip())
    words = cleaned.split()
    candidates: List[str] = []

    if words:
        first_word_slug = _NON_ALNUM_RE.sub("", words[0].lower())
        if first_word_slug:
            candidates.append(first_word_slug)

    no_space_slug = _NON_ALNUM_RE.sub("", cleaned.lower())
    if no_space_slug and no_space_slug not in candidates:
        candidates.append(no_space_slug)

    hyphenated_slug = re.sub(r"[^a-z0-9]+", "-", cleaned.lower()).strip("-")
    if hyphenated_slug and hyphenated_slug not in candidates:
        candidates.append(hyphenated_slug)

    return candidates


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def find_title_match(target_title: str, candidate_jobs: List[Job]) -> Optional[Job]:
    """Find a confident title match within a company's board listing.

    Only an exact match, after normalizing case/punctuation/whitespace,
    counts as confident enough to trust - deliberately conservative, to
    avoid enriching one posting with a different (if similarly-titled)
    role at the same company.
    """
    normalized_target = _normalize_title(target_title)
    if not normalized_target:
        return None
    for job in candidate_jobs:
        if _normalize_title(job.title) == normalized_target:
            return job
    return None


def _try_greenhouse(slug: str) -> Optional[List[Job]]:
    try:
        jobs = GreenhouseJobSource(board_token=slug).fetch_jobs()
        return jobs if jobs else None
    except JobSourceError:
        return None


def _try_lever(slug: str) -> Optional[List[Job]]:
    try:
        jobs = LeverJobSource(company_slug=slug).fetch_jobs()
        return jobs if jobs else None
    except JobSourceError:
        return None


def enrich_jobs(jobs: List[Job], max_companies: int = 20) -> List[Job]:
    """Best-effort enrichment of Adzuna-discovered jobs, in place.

    For up to `max_companies` distinct companies among `jobs` (capped so
    a large discovery run doesn't send lookups to Greenhouse/Lever for
    companies that almost certainly aren't there), tries to find that
    company's board and swap in a matched posting's direct URL and full
    description. Every job in `jobs` is returned regardless of whether
    enrichment succeeded for it.
    """
    company_board_cache: Dict[str, Optional[List[Job]]] = {}
    attempted_companies = 0

    for job in jobs:
        company_key = job.company.strip().lower()

        if company_key not in company_board_cache:
            if attempted_companies >= max_companies:
                continue  # over the cap for this run - leave as Adzuna reported it
            attempted_companies += 1

            board_jobs = None
            for slug in slug_candidates(job.company):
                board_jobs = _try_greenhouse(slug) or _try_lever(slug)
                if board_jobs:
                    break
            company_board_cache[company_key] = board_jobs

        board_jobs = company_board_cache.get(company_key)
        if not board_jobs:
            continue

        match = find_title_match(job.title, board_jobs)
        if match is None:
            continue

        job.url = match.url
        job.description = match.description
        job.is_remote = match.is_remote or job.is_remote
        logger.info(
            "Enriched Adzuna job '%s' at %s with a direct %s posting.",
            job.title, job.company, match.source.value,
        )

    return jobs
