from unittest.mock import patch

from jobsearch.models import Job, SourceType
from jobsearch.sources.base import JobSourceError
from jobsearch.sources.enrichment import enrich_jobs, find_title_match, slug_candidates


def _job(company="Acme", title="AI/ML Engineer", source=SourceType.ADZUNA, url="https://adzuna.example/1"):
    return Job(
        source=source,
        source_job_id="1",
        company=company,
        title=title,
        location="New York, NY",
        url=url,
        description="original description",
    )


# --- slug_candidates ---------------------------------------------------------


def test_slug_candidates_simple_name():
    assert slug_candidates("Stripe") == ["stripe"]


def test_slug_candidates_strips_legal_suffix():
    candidates = slug_candidates("Notion Labs, Inc.")
    assert "notion" in candidates
    assert candidates[0] == "notion"  # first-word guess should be tried first


def test_slug_candidates_multi_word_no_suffix():
    candidates = slug_candidates("Coca-Cola Company")
    assert "cocacola" in candidates


def test_slug_candidates_empty_string_returns_empty_list():
    assert slug_candidates("") == []


def test_slug_candidates_deduplicates_variants():
    candidates = slug_candidates("Stripe")
    assert len(candidates) == len(set(candidates))


# --- find_title_match ---------------------------------------------------------


def test_find_title_match_exact_after_normalization():
    board_job = _job(title="AI/ML  Engineer!!", source=SourceType.GREENHOUSE)
    match = find_title_match("ai/ml engineer", [board_job])
    assert match is board_job


def test_find_title_match_returns_none_when_no_match():
    board_job = _job(title="Completely Different Role", source=SourceType.GREENHOUSE)
    assert find_title_match("AI/ML Engineer", [board_job]) is None


def test_find_title_match_returns_none_for_empty_title():
    board_job = _job(title="AI/ML Engineer", source=SourceType.GREENHOUSE)
    assert find_title_match("", [board_job]) is None


def test_find_title_match_with_empty_candidate_list():
    assert find_title_match("AI/ML Engineer", []) is None


# --- enrich_jobs: success path ------------------------------------------------


def test_enrich_jobs_updates_url_and_description_on_match():
    adzuna_job = _job(url="https://adzuna.example/redirect/1", title="AI/ML Engineer")
    direct_job = _job(
        title="AI/ML Engineer", source=SourceType.GREENHOUSE, url="https://boards.greenhouse.io/acme/1"
    )
    direct_job.description = "full HTML description from the company itself"

    with patch("jobsearch.sources.enrichment._try_greenhouse", return_value=[direct_job]), \
         patch("jobsearch.sources.enrichment._try_lever", return_value=None):
        result = enrich_jobs([adzuna_job], max_companies=20)

    assert result[0].url == "https://boards.greenhouse.io/acme/1"
    assert result[0].description == "full HTML description from the company itself"


def test_enrich_jobs_tries_lever_when_greenhouse_fails():
    adzuna_job = _job(title="Backend Engineer")
    lever_job = _job(title="Backend Engineer", source=SourceType.LEVER, url="https://jobs.lever.co/acme/1")

    with patch("jobsearch.sources.enrichment._try_greenhouse", return_value=None), \
         patch("jobsearch.sources.enrichment._try_lever", return_value=[lever_job]):
        result = enrich_jobs([adzuna_job], max_companies=20)

    assert result[0].url == "https://jobs.lever.co/acme/1"


# --- enrich_jobs: graceful fallback (never drops a job) -----------------------


def test_enrich_jobs_preserves_job_when_no_board_found():
    adzuna_job = _job(url="https://adzuna.example/redirect/1")
    original_description = adzuna_job.description

    with patch("jobsearch.sources.enrichment._try_greenhouse", return_value=None), \
         patch("jobsearch.sources.enrichment._try_lever", return_value=None):
        result = enrich_jobs([adzuna_job], max_companies=20)

    assert len(result) == 1  # never dropped
    assert result[0].url == "https://adzuna.example/redirect/1"
    assert result[0].description == original_description


def test_enrich_jobs_preserves_job_when_board_found_but_no_title_match():
    adzuna_job = _job(title="AI/ML Engineer", url="https://adzuna.example/redirect/1")
    unrelated_job = _job(title="Sales Representative", source=SourceType.GREENHOUSE)

    with patch("jobsearch.sources.enrichment._try_greenhouse", return_value=[unrelated_job]), \
         patch("jobsearch.sources.enrichment._try_lever", return_value=None):
        result = enrich_jobs([adzuna_job], max_companies=20)

    assert result[0].url == "https://adzuna.example/redirect/1"  # unchanged


def test_enrich_jobs_handles_lookup_raising_job_source_error():
    adzuna_job = _job()
    with patch(
        "jobsearch.sources.enrichment.GreenhouseJobSource.fetch_jobs",
        side_effect=JobSourceError("simulated 404"),
    ), patch(
        "jobsearch.sources.enrichment.LeverJobSource.fetch_jobs",
        side_effect=JobSourceError("simulated 404"),
    ):
        result = enrich_jobs([adzuna_job], max_companies=20)

    assert len(result) == 1
    assert result[0].url == adzuna_job.url


# --- enrich_jobs: caching + cap -----------------------------------------------


def test_enrich_jobs_only_looks_up_each_company_once():
    job_a = _job(title="AI/ML Engineer")
    job_a.source_job_id = "a"
    job_b = _job(title="Backend Engineer")
    job_b.source_job_id = "b"  # same company as job_a

    with patch("jobsearch.sources.enrichment._try_greenhouse", return_value=None) as mock_gh, \
         patch("jobsearch.sources.enrichment._try_lever", return_value=None):
        enrich_jobs([job_a, job_b], max_companies=20)

    # "Acme" only produces one slug candidate ("acme"), so exactly one
    # Greenhouse lookup should happen despite two jobs from that company.
    assert mock_gh.call_count == 1


def test_enrich_jobs_respects_max_companies_cap():
    jobs = [_job(company=f"Company{i}", title=f"Role {i}") for i in range(5)]
    for i, job in enumerate(jobs):
        job.source_job_id = str(i)

    with patch("jobsearch.sources.enrichment._try_greenhouse", return_value=None) as mock_gh, \
         patch("jobsearch.sources.enrichment._try_lever", return_value=None):
        enrich_jobs(jobs, max_companies=2)

    # Only the first 2 distinct companies should have been attempted.
    assert mock_gh.call_count == 2


def test_enrich_jobs_returns_all_jobs_even_when_cap_exceeded():
    jobs = [_job(company=f"Company{i}", title=f"Role {i}") for i in range(5)]
    for i, job in enumerate(jobs):
        job.source_job_id = str(i)

    with patch("jobsearch.sources.enrichment._try_greenhouse", return_value=None), \
         patch("jobsearch.sources.enrichment._try_lever", return_value=None):
        result = enrich_jobs(jobs, max_companies=2)

    assert len(result) == 5  # nothing dropped just because it hit the cap


def test_enrich_jobs_empty_list():
    assert enrich_jobs([], max_companies=20) == []
