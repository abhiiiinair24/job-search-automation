from unittest.mock import Mock, patch

import requests

from jobsearch.models import SourceType
from jobsearch.sources.adzuna import AdzunaDiscoverySource
from jobsearch.sources.base import JobSourceError

SAMPLE_RESULT = {
    "id": "111",
    "title": "AI/ML Engineer",
    "company": {"display_name": "Acme Corp"},
    "location": {"display_name": "New York, NY"},
    "description": "Build ML systems for our platform.",
    "redirect_url": "https://www.adzuna.com/land/ad/111",
    "created": "2026-09-05T12:00:00Z",
}


def _mock_response(json_data, status_code=200, raise_for_status_error=None):
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.side_effect = raise_for_status_error
    return resp


def _no_enrichment_patches():
    return (
        patch("jobsearch.sources.enrichment._try_greenhouse", return_value=None),
        patch("jobsearch.sources.enrichment._try_lever", return_value=None),
    )


# --- basic parsing ------------------------------------------------------


@patch("jobsearch.sources.adzuna.requests.get")
def test_fetch_jobs_parses_valid_result(mock_get):
    mock_get.return_value = _mock_response({"results": [SAMPLE_RESULT]})
    gh, lv = _no_enrichment_patches()
    with gh, lv:
        source = AdzunaDiscoverySource(app_id="id", app_key="key", search_terms=["ai/ml engineer"])
        jobs = source.fetch_jobs()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == SourceType.ADZUNA
    assert job.source_job_id == "111"
    assert job.company == "Acme Corp"
    assert job.title == "AI/ML Engineer"
    assert job.location == "New York, NY"
    assert job.url == "https://www.adzuna.com/land/ad/111"
    assert job.date_posted is not None
    assert job.stable_id == "adzuna:111"


@patch("jobsearch.sources.adzuna.requests.get")
def test_fetch_jobs_requests_us_country_and_max_days_old(mock_get):
    mock_get.return_value = _mock_response({"results": []})
    source = AdzunaDiscoverySource(
        app_id="id", app_key="key", search_terms=["backend engineer"], max_days_old=4
    )
    source.fetch_jobs()

    called_url = mock_get.call_args.args[0]
    called_params = mock_get.call_args.kwargs["params"]
    assert "/jobs/us/search/1" in called_url
    assert called_params["max_days_old"] == 4
    assert called_params["what"] == "backend engineer"


@patch("jobsearch.sources.adzuna.requests.get")
def test_fetch_jobs_empty_results_returns_empty_list(mock_get):
    mock_get.return_value = _mock_response({"results": []})
    source = AdzunaDiscoverySource(app_id="id", app_key="key", search_terms=["data engineer"])
    assert source.fetch_jobs() == []


@patch("jobsearch.sources.adzuna.requests.get")
def test_fetch_jobs_skips_malformed_result_without_crashing(mock_get):
    malformed = {"title": "Missing ID field"}  # no "id" key
    mock_get.return_value = _mock_response({"results": [malformed, SAMPLE_RESULT]})
    gh, lv = _no_enrichment_patches()
    with gh, lv:
        source = AdzunaDiscoverySource(app_id="id", app_key="key", search_terms=["data engineer"])
        jobs = source.fetch_jobs()

    assert len(jobs) == 1
    assert jobs[0].source_job_id == "111"


# --- multi-term querying + dedup -----------------------------------------


@patch("jobsearch.sources.adzuna.requests.get")
def test_fetch_jobs_queries_once_per_search_term(mock_get):
    mock_get.return_value = _mock_response({"results": []})
    terms = ["ai/ml engineer", "backend engineer", "data engineer"]
    source = AdzunaDiscoverySource(app_id="id", app_key="key", search_terms=terms)
    source.fetch_jobs()
    assert mock_get.call_count == len(terms)


@patch("jobsearch.sources.adzuna.requests.get")
def test_fetch_jobs_dedupes_same_job_across_multiple_terms(mock_get):
    # Both search terms happen to return the same underlying posting.
    mock_get.return_value = _mock_response({"results": [SAMPLE_RESULT]})
    gh, lv = _no_enrichment_patches()
    with gh, lv:
        source = AdzunaDiscoverySource(
            app_id="id", app_key="key", search_terms=["ai/ml engineer", "genai engineer"]
        )
        jobs = source.fetch_jobs()

    assert mock_get.call_count == 2
    assert len(jobs) == 1  # deduped, not two copies


# --- per-term fault tolerance ---------------------------------------------


@patch("jobsearch.sources.adzuna.requests.get")
def test_fetch_jobs_one_failed_term_does_not_stop_others(mock_get):
    def side_effect(url, params=None, timeout=None):
        if params["what"] == "backend engineer":
            raise requests.ConnectionError("simulated failure")
        return _mock_response({"results": [SAMPLE_RESULT]})

    mock_get.side_effect = side_effect
    gh, lv = _no_enrichment_patches()
    with gh, lv:
        source = AdzunaDiscoverySource(
            app_id="id", app_key="key", search_terms=["backend engineer", "ai/ml engineer"]
        )
        jobs = source.fetch_jobs()

    assert len(jobs) == 1  # the succeeding term's result still came through


@patch("jobsearch.sources.adzuna.requests.get")
def test_fetch_jobs_raises_only_when_every_term_fails(mock_get):
    mock_get.side_effect = requests.ConnectionError("simulated failure")
    source = AdzunaDiscoverySource(
        app_id="id", app_key="key", search_terms=["backend engineer", "ai/ml engineer"]
    )
    try:
        source.fetch_jobs()
        assert False, "expected JobSourceError"
    except JobSourceError:
        pass


@patch("jobsearch.sources.adzuna.requests.get")
def test_safe_fetch_jobs_swallows_total_failure(mock_get):
    mock_get.side_effect = requests.ConnectionError("simulated failure")
    source = AdzunaDiscoverySource(app_id="id", app_key="key", search_terms=["backend engineer"])
    assert source.safe_fetch_jobs() == []


def test_fetch_jobs_with_no_search_terms_returns_empty_without_network_call():
    with patch("jobsearch.sources.adzuna.requests.get") as mock_get:
        source = AdzunaDiscoverySource(app_id="id", app_key="key", search_terms=[])
        jobs = source.fetch_jobs()
    assert jobs == []
    mock_get.assert_not_called()


# --- enrichment toggle -----------------------------------------------------


@patch("jobsearch.sources.adzuna.enrich_jobs")
@patch("jobsearch.sources.adzuna.requests.get")
def test_fetch_jobs_calls_enrichment_when_enabled(mock_get, mock_enrich):
    mock_get.return_value = _mock_response({"results": [SAMPLE_RESULT]})
    mock_enrich.side_effect = lambda jobs, max_companies: jobs

    source = AdzunaDiscoverySource(
        app_id="id", app_key="key", search_terms=["ai/ml engineer"], enrich=True
    )
    source.fetch_jobs()

    mock_enrich.assert_called_once()


@patch("jobsearch.sources.adzuna.enrich_jobs")
@patch("jobsearch.sources.adzuna.requests.get")
def test_fetch_jobs_skips_enrichment_when_disabled(mock_get, mock_enrich):
    mock_get.return_value = _mock_response({"results": [SAMPLE_RESULT]})

    source = AdzunaDiscoverySource(
        app_id="id", app_key="key", search_terms=["ai/ml engineer"], enrich=False
    )
    source.fetch_jobs()

    mock_enrich.assert_not_called()
