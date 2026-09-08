"""Orchestration: fetch from all sources, filter, dedup, and rank."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from jobsearch.config import Config
from jobsearch.dedup import deduplicate_jobs
from jobsearch.filters.experience import annotate_experience, passes_experience_filter
from jobsearch.filters.location import is_us_based
from jobsearch.filters.recency import is_recent
from jobsearch.filters.sponsorship import annotate_sponsorship
from jobsearch.models import Job, SourceType
from jobsearch.profile import CandidateProfile, default_profile
from jobsearch.ranking import RankingWeights, rank_jobs
from jobsearch.seen_store import SeenJobStore
from jobsearch.sources.adzuna import AdzunaDiscoverySource
from jobsearch.sources.base import JobSource
from jobsearch.sources.greenhouse import GreenhouseJobSource
from jobsearch.sources.lever import LeverJobSource

logger = logging.getLogger(__name__)


def build_sources(config: Config, profile: Optional[CandidateProfile] = None) -> List[JobSource]:
    """Construct every configured job source.

    Adzuna (the primary discovery mechanism) is added whenever
    ADZUNA_APP_ID/ADZUNA_APP_KEY are configured — search terms default to
    the candidate profile's target roles unless config.adzuna_search_terms
    overrides them. Greenhouse/Lever direct-watch entries (from
    config/boards.json, optional) are added exactly as before — discovery
    and direct-watch are additive, not exclusive.
    """
    sources: List[JobSource] = []

    for board in config.greenhouse_boards:
        sources.append(GreenhouseJobSource(board_token=board))
    for company in config.lever_companies:
        sources.append(LeverJobSource(company_slug=company))

    if config.adzuna_app_id and config.adzuna_app_key:
        search_terms = config.adzuna_search_terms
        if not search_terms:
            profile = profile or default_profile(years_of_experience=config.candidate_experience_years)
            search_terms = list(profile.target_roles.keys())

        if search_terms:
            sources.append(
                AdzunaDiscoverySource(
                    app_id=config.adzuna_app_id,
                    app_key=config.adzuna_app_key,
                    search_terms=search_terms,
                    max_days_old=config.adzuna_max_days_old,
                    results_per_page=config.adzuna_results_per_page,
                    enrich=config.adzuna_enrich,
                    enrichment_max_companies=config.adzuna_enrichment_max_companies,
                )
            )
        else:
            logger.warning("Adzuna credentials configured but no search terms available; skipping.")
    else:
        logger.warning(
            "ADZUNA_APP_ID/ADZUNA_APP_KEY not configured - job discovery is disabled; "
            "only direct-watch sources (config/boards.json) will be used, if any."
        )

    return sources


@dataclass
class SearchResult:
    jobs: List[Job]
    total_fetched: int
    total_after_filters: int
    failed_sources: List[str]
    # Populated only when a seen_store is passed to run_search(); otherwise
    # new_jobs == jobs and already_seen_jobs is empty. Nothing is marked as
    # seen automatically — call seen_store.mark_seen(...) once a caller has
    # actually acted on (e.g. emailed) the new jobs.
    new_jobs: List[Job] = field(default_factory=list)
    already_seen_jobs: List[Job] = field(default_factory=list)


def run_search(
    config: Config,
    sources: Optional[List[JobSource]] = None,
    reference_time: Optional[datetime] = None,
    profile: Optional[CandidateProfile] = None,
    seen_store: Optional[SeenJobStore] = None,
) -> SearchResult:
    """Run the full pipeline: fetch -> dedup -> annotate -> filter -> rank.

    `sources` can be injected directly (used heavily in tests, and useful
    for anyone wiring in a source that isn't Greenhouse/Lever); otherwise
    sources are built from `config`.

    `profile` lets a caller rank against a different/updated
    CandidateProfile; otherwise the default profile is built from `config`.

    `seen_store` lets a caller split results into new-vs-already-seen jobs
    (see SearchResult.new_jobs / already_seen_jobs) using a SeenJobStore.
    This is purely additive — passing None preserves prior behavior.
    """
    profile = profile or default_profile(years_of_experience=config.candidate_experience_years)
    sources = sources if sources is not None else build_sources(config, profile=profile)

    all_jobs: List[Job] = []
    failed_sources: List[str] = []

    for source in sources:
        fetched = source.safe_fetch_jobs()
        if not fetched:
            # safe_fetch_jobs already logs the underlying error (if any); we
            # just track which sources produced nothing so it's visible in
            # the run summary too.
            failed_sources.append(source.name)
        all_jobs.extend(fetched)

    total_fetched = len(all_jobs)
    deduped = deduplicate_jobs(all_jobs)

    filtered: List[Job] = []
    for job in deduped:
        annotate_experience(job)
        annotate_sponsorship(job)

        # Adzuna jobs are already US-scoped by the source itself (its
        # /v1/api/jobs/us/search endpoint), so the free-text is_us_based()
        # heuristic is skipped for them - it was built for Greenhouse/Lever
        # location strings ("City, ST") and doesn't reliably parse Adzuna's
        # US format ("City, County", e.g. "Tampa, Hillsborough County"),
        # which caused false negatives dropping nearly all Adzuna results.
        # Greenhouse/Lever jobs (which can span multiple countries) still
        # go through the heuristic exactly as before.
        if job.source != SourceType.ADZUNA and not is_us_based(job):
            continue
        if not is_recent(job, reference_time=reference_time, max_age_days=config.recency_days):
            continue
        if not passes_experience_filter(job, hard_exclude_years=config.hard_exclude_experience_years):
            continue

        filtered.append(job)

    weights = RankingWeights(profile=profile)
    ranked = rank_jobs(filtered, weights=weights)

    new_jobs = ranked
    already_seen_jobs: List[Job] = []
    if seen_store is not None:
        seen_ids = seen_store.get_seen_ids()
        new_jobs = [job for job in ranked if job.stable_id not in seen_ids]
        already_seen_jobs = [job for job in ranked if job.stable_id in seen_ids]

    return SearchResult(
        jobs=ranked,
        total_fetched=total_fetched,
        total_after_filters=len(ranked),
        failed_sources=failed_sources,
        new_jobs=new_jobs,
        already_seen_jobs=already_seen_jobs,
    )
