from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import patch

from jobsearch.config import Config
from jobsearch.engine import build_sources, run_search
from jobsearch.models import Job, SourceType
from jobsearch.profile import CandidateProfile, default_profile
from jobsearch.seen_store import InMemorySeenJobStore
from jobsearch.sources.adzuna import AdzunaDiscoverySource
from jobsearch.sources.base import JobSource, JobSourceError
from jobsearch.sources.greenhouse import GreenhouseJobSource
from jobsearch.sources.lever import LeverJobSource


class FakeSource(JobSource):
    """A JobSource stub for testing the engine pipeline without any network calls."""

    def __init__(self, name: str, jobs: List[Job] = None, should_fail: bool = False):
        self.name = name
        self._jobs = jobs or []
        self._should_fail = should_fail

    def fetch_jobs(self) -> List[Job]:
        if self._should_fail:
            raise JobSourceError("simulated failure")
        return self._jobs


def _job(
    source_job_id,
    title,
    description,
    location="Remote - US",
    company="Acme",
    days_ago=1,
    now=None,
):
    now = now or datetime.now(timezone.utc)
    return Job(
        source=SourceType.GREENHOUSE,
        source_job_id=source_job_id,
        company=company,
        title=title,
        location=location,
        url=f"https://example.com/{source_job_id}",
        description=description,
        date_posted=now - timedelta(days=days_ago),
        date_updated=now - timedelta(days=days_ago),
    )


def test_run_search_filters_recency_experience_and_location():
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)

    good_job = _job("1", "AI/ML Engineer", "3-5 years experience. RAG, LangChain, AWS.", days_ago=1, now=now)
    stale_job = _job("2", "Backend Engineer", "3-5 years experience. Java, Kafka.", days_ago=30, now=now)
    senior_job = _job("3", "Staff Engineer", "Requires 8+ years of experience.", days_ago=1, now=now)
    non_us_job = _job("4", "Data Engineer", "3-5 years experience.", location="Bangalore, India", days_ago=1, now=now)

    source = FakeSource("fake", jobs=[good_job, stale_job, senior_job, non_us_job])
    config = Config(recency_days=4, hard_exclude_experience_years=6, candidate_experience_years=4)

    result = run_search(config, sources=[source], reference_time=now)

    titles = {job.title for job in result.jobs}
    assert "AI/ML Engineer" in titles
    assert "Backend Engineer" not in titles  # too stale
    assert "Staff Engineer" not in titles  # requires 8+ years
    assert "Data Engineer" not in titles  # non-US location


def test_run_search_deduplicates_across_sources():
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    job_a = _job("dup-1", "Backend Engineer", "3-5 years. Java.", days_ago=1, now=now)
    job_b = _job("dup-1", "Backend Engineer", "3-5 years. Java.", days_ago=1, now=now)  # same source_job_id

    source = FakeSource("fake", jobs=[job_a, job_b])
    config = Config()

    result = run_search(config, sources=[source], reference_time=now)

    assert len(result.jobs) == 1


def test_run_search_tracks_failed_sources_without_crashing():
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    good_source = FakeSource(
        "good", jobs=[_job("1", "AI/ML Engineer", "3-5 years. RAG, PyTorch.", days_ago=1, now=now)]
    )
    broken_source = FakeSource("broken", should_fail=True)

    config = Config()
    result = run_search(config, sources=[good_source, broken_source], reference_time=now)

    assert "broken" in result.failed_sources
    assert len(result.jobs) == 1


def test_run_search_ranks_best_fit_first():
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    strong = _job("1", "AI/ML Engineer", "RAG, LangChain, PyTorch, Kafka, AWS. 3-5 years.", days_ago=1, now=now)
    weak = _job("2", "Software Engineer", "General role.", days_ago=1, now=now)

    source = FakeSource("fake", jobs=[weak, strong])
    config = Config()

    result = run_search(config, sources=[source], reference_time=now)

    assert result.jobs[0].title == "AI/ML Engineer"


def test_run_search_with_no_jobs_returns_empty_result():
    config = Config()
    source = FakeSource("empty", jobs=[])
    result = run_search(config, sources=[source])
    assert result.jobs == []
    assert result.total_fetched == 0


def test_run_search_uses_injected_profile_for_ranking():
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    rust_job = _job("1", "Backend Engineer", "We use Rust extensively. 3-5 years.", days_ago=1, now=now)
    java_job = _job("2", "Backend Engineer", "We use Java extensively. 3-5 years.", days_ago=1, now=now)

    custom_profile = CandidateProfile(
        years_of_experience=4.0,
        skills={"rust": 5.0},
        target_roles={},
        domain_experience=[],
        projects=[],
    )

    source = FakeSource("fake", jobs=[java_job, rust_job])
    config = Config()

    result = run_search(config, sources=[source], reference_time=now, profile=custom_profile)

    assert result.jobs[0].title == "Backend Engineer"
    assert result.jobs[0].description.startswith("We use Rust")


def test_run_search_prioritizes_buffalo_jobs_end_to_end():
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    strong_elsewhere = _job(
        "1", "AI/ML Engineer", "RAG, LangChain, PyTorch, Kafka, AWS. 3-5 years.",
        location="San Francisco, CA", days_ago=1, now=now,
    )
    weak_in_buffalo = _job(
        "2", "Software Engineer", "General role, no strong overlap. 3-5 years.",
        location="Buffalo, NY", days_ago=1, now=now,
    )

    source = FakeSource("fake", jobs=[strong_elsewhere, weak_in_buffalo])
    config = Config()

    # Using the real default profile (which prioritizes Buffalo) end to end.
    result = run_search(config, sources=[source], reference_time=now)

    assert result.jobs[0].location == "Buffalo, NY"


# --- seen-job tracking integration ------------------------------------------


def test_run_search_without_seen_store_treats_all_jobs_as_new():
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    job = _job("1", "AI/ML Engineer", "3-5 years. RAG, PyTorch.", days_ago=1, now=now)

    result = run_search(Config(), sources=[FakeSource("fake", jobs=[job])], reference_time=now)

    assert len(result.new_jobs) == 1
    assert result.already_seen_jobs == []


def test_run_search_with_seen_store_splits_new_and_seen_jobs():
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    seen_job = _job("1", "AI/ML Engineer", "3-5 years. RAG, PyTorch.", days_ago=1, now=now)
    new_job = _job("2", "Backend Engineer", "3-5 years. Java, Kafka.", days_ago=1, now=now)

    seen_store = InMemorySeenJobStore(initial_seen=[seen_job.stable_id])

    result = run_search(
        Config(),
        sources=[FakeSource("fake", jobs=[seen_job, new_job])],
        reference_time=now,
        seen_store=seen_store,
    )

    new_titles = {job.title for job in result.new_jobs}
    seen_titles = {job.title for job in result.already_seen_jobs}
    assert new_titles == {"Backend Engineer"}
    assert seen_titles == {"AI/ML Engineer"}
    # `jobs` (the full ranked list) always contains everything regardless
    # of seen status.
    assert len(result.jobs) == 2


def test_run_search_does_not_mutate_seen_store_by_itself():
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    job = _job("1", "AI/ML Engineer", "3-5 years. RAG, PyTorch.", days_ago=1, now=now)
    seen_store = InMemorySeenJobStore()

    run_search(
        Config(),
        sources=[FakeSource("fake", jobs=[job])],
        reference_time=now,
        seen_store=seen_store,
    )

    # run_search only reads from the store; marking-as-seen is a separate,
    # explicit step a caller performs after acting on the results.
    assert seen_store.get_seen_ids() == set()


# --- build_sources: Adzuna discovery wiring ----------------------------------


def test_build_sources_includes_adzuna_when_credentials_present():
    config = Config(adzuna_app_id="id", adzuna_app_key="key", adzuna_search_terms=["backend engineer"])
    sources = build_sources(config)
    adzuna_sources = [s for s in sources if isinstance(s, AdzunaDiscoverySource)]
    assert len(adzuna_sources) == 1


def test_build_sources_skips_adzuna_when_credentials_absent():
    config = Config(adzuna_app_id=None, adzuna_app_key=None)
    sources = build_sources(config)
    assert not any(isinstance(s, AdzunaDiscoverySource) for s in sources)


def test_build_sources_skips_adzuna_when_only_one_credential_present():
    config = Config(adzuna_app_id="id", adzuna_app_key=None)
    sources = build_sources(config)
    assert not any(isinstance(s, AdzunaDiscoverySource) for s in sources)


def test_build_sources_uses_explicit_search_terms_when_configured():
    config = Config(
        adzuna_app_id="id", adzuna_app_key="key", adzuna_search_terms=["custom role"]
    )
    sources = build_sources(config)
    adzuna_source = next(s for s in sources if isinstance(s, AdzunaDiscoverySource))
    assert adzuna_source.search_terms == ["custom role"]


def test_build_sources_derives_search_terms_from_profile_when_unset():
    config = Config(adzuna_app_id="id", adzuna_app_key="key", adzuna_search_terms=[])
    profile = CandidateProfile(
        years_of_experience=4.0,
        skills={},
        target_roles={"ai/ml engineer": 3.0, "backend engineer": 2.0},
        domain_experience=[],
        projects=[],
    )
    sources = build_sources(config, profile=profile)
    adzuna_source = next(s for s in sources if isinstance(s, AdzunaDiscoverySource))
    assert set(adzuna_source.search_terms) == {"ai/ml engineer", "backend engineer"}


def test_build_sources_derives_search_terms_from_default_profile_when_no_profile_given():
    config = Config(adzuna_app_id="id", adzuna_app_key="key", adzuna_search_terms=[])
    sources = build_sources(config)  # no profile passed
    adzuna_source = next(s for s in sources if isinstance(s, AdzunaDiscoverySource))
    expected_terms = set(default_profile().target_roles.keys())
    assert set(adzuna_source.search_terms) == expected_terms


def test_build_sources_still_includes_greenhouse_and_lever_direct_watch():
    config = Config(
        greenhouse_boards=["stripe"],
        lever_companies=["netflix"],
        adzuna_app_id="id",
        adzuna_app_key="key",
        adzuna_search_terms=["backend engineer"],
    )
    sources = build_sources(config)
    assert any(isinstance(s, GreenhouseJobSource) for s in sources)
    assert any(isinstance(s, LeverJobSource) for s in sources)
    assert any(isinstance(s, AdzunaDiscoverySource) for s in sources)


def test_build_sources_greenhouse_lever_work_standalone_without_adzuna():
    # Direct-watch must keep working even with zero Adzuna configuration -
    # discovery and direct-watch are independent, not coupled.
    config = Config(greenhouse_boards=["stripe"], adzuna_app_id=None, adzuna_app_key=None)
    sources = build_sources(config)
    assert len(sources) == 1
    assert isinstance(sources[0], GreenhouseJobSource)


def test_build_sources_passes_adzuna_tuning_config_through():
    config = Config(
        adzuna_app_id="id",
        adzuna_app_key="key",
        adzuna_search_terms=["backend engineer"],
        adzuna_max_days_old=7,
        adzuna_results_per_page=10,
        adzuna_enrich=False,
        adzuna_enrichment_max_companies=5,
    )
    sources = build_sources(config)
    adzuna_source = next(s for s in sources if isinstance(s, AdzunaDiscoverySource))
    assert adzuna_source.max_days_old == 7
    assert adzuna_source.results_per_page == 10
    assert adzuna_source.enrich is False
    assert adzuna_source.enrichment_max_companies == 5


def test_run_search_end_to_end_with_mocked_adzuna_source():
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    adzuna_job = Job(
        source=SourceType.ADZUNA,
        source_job_id="1",
        company="DiscoveredCo",
        title="AI/ML Engineer",
        location="Buffalo, NY",
        url="https://adzuna.example/redirect/1",
        description="RAG, LangChain, PyTorch. 3-5 years.",
        date_posted=now - timedelta(days=1),
        date_updated=now - timedelta(days=1),
    )

    with patch.object(AdzunaDiscoverySource, "fetch_jobs", return_value=[adzuna_job]):
        adzuna_source = AdzunaDiscoverySource(
            app_id="id", app_key="key", search_terms=["ai/ml engineer"]
        )
        result = run_search(Config(), sources=[adzuna_source], reference_time=now)

    assert len(result.jobs) == 1
    assert result.jobs[0].company == "DiscoveredCo"


# --- regression: Adzuna US-location false negatives ("City, County" format) -


def test_run_search_accepts_real_adzuna_county_style_us_locations():
    # Real location strings observed from Adzuna's live US index - these
    # use "City, County" rather than "City, ST", which the free-text
    # is_us_based() heuristic (built for Greenhouse/Lever) cannot parse.
    # Adzuna jobs must bypass that heuristic since the source itself is
    # already US-scoped (/v1/api/jobs/us/search).
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    real_adzuna_locations = [
        "Watkins, Aurora",
        "King of Prussia, Montgomery County",
        "Tampa, Hillsborough County",
        "South San Francisco, San Mateo County",
        "Jersey City, Hudson County",
        "Washington, Washington, D.C.",
        "Ny State Campus, Albany County",
    ]
    jobs = [
        _job(str(i), "Backend Engineer", "3-5 years. Python.", location=loc, days_ago=1, now=now)
        for i, loc in enumerate(real_adzuna_locations)
    ]
    for job in jobs:
        job.source = SourceType.ADZUNA

    result = run_search(Config(), sources=[FakeSource("fake", jobs)], reference_time=now)

    assert len(result.jobs) == len(real_adzuna_locations)


def test_run_search_still_filters_non_us_greenhouse_locations():
    # Regression guard: the Adzuna bypass must NOT weaken filtering for
    # Greenhouse/Lever jobs, which can legitimately span countries.
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    us_job = _job("1", "Backend Engineer", "3-5 years.", location="Austin, TX", days_ago=1, now=now)
    non_us_job = _job("2", "Backend Engineer", "3-5 years.", location="London, UK", days_ago=1, now=now)
    # both default to SourceType.GREENHOUSE via the _job() helper

    result = run_search(Config(), sources=[FakeSource("fake", [us_job, non_us_job])], reference_time=now)

    assert len(result.jobs) == 1
    assert result.jobs[0].location == "Austin, TX"


def test_run_search_filters_non_us_adzuna_location_with_explicit_country():
    # Even though Adzuna jobs bypass the heuristic, this confirms the
    # bypass is keyed on job.source == ADZUNA specifically, not applied
    # blanket to everything - a non-Adzuna source with a non-US location
    # (here relabeled as LEVER) is still correctly filtered out.
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    job = _job("1", "Backend Engineer", "3-5 years.", location="London, UK", days_ago=1, now=now)
    job.source = SourceType.LEVER

    result = run_search(Config(), sources=[FakeSource("fake", [job])], reference_time=now)

    assert result.jobs == []
