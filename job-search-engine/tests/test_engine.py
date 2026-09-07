from datetime import datetime, timedelta, timezone
from typing import List

from jobsearch.config import Config
from jobsearch.engine import run_search
from jobsearch.models import Job, SourceType
from jobsearch.profile import CandidateProfile
from jobsearch.seen_store import InMemorySeenJobStore
from jobsearch.sources.base import JobSource, JobSourceError


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
