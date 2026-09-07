from unittest.mock import Mock, patch

import requests

from jobsearch.models import SourceType
from jobsearch.sources.base import JobSourceError
from jobsearch.sources.lever import LeverJobSource

SAMPLE_PAYLOAD = [
    {
        "id": "abc-123",
        "text": "Data Engineer",
        "categories": {"location": "New York, NY", "team": "Data"},
        "hostedUrl": "https://jobs.lever.co/acme/abc-123",
        "descriptionPlain": "4+ years of experience with PySpark and BigQuery.",
        "createdAt": 1757116800000,  # 2025-09-06 in epoch millis
    }
]


def _mock_response(json_data, status_code=200, raise_for_status_error=None):
    mock_resp = Mock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    if raise_for_status_error:
        mock_resp.raise_for_status.side_effect = raise_for_status_error
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


@patch("jobsearch.sources.lever.requests.get")
def test_fetch_jobs_parses_valid_postings(mock_get):
    mock_get.return_value = _mock_response(SAMPLE_PAYLOAD)
    source = LeverJobSource(company_slug="acme")

    jobs = source.fetch_jobs()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == SourceType.LEVER
    assert job.source_job_id == "abc-123"
    assert job.company == "acme"
    assert job.title == "Data Engineer"
    assert job.location == "New York, NY"
    assert job.is_remote is False
    assert "PySpark" in job.description
    assert job.date_posted is not None


@patch("jobsearch.sources.lever.requests.get")
def test_fetch_jobs_uses_company_name_override(mock_get):
    mock_get.return_value = _mock_response(SAMPLE_PAYLOAD)
    source = LeverJobSource(company_slug="acme", company_name="Acme Corp")

    jobs = source.fetch_jobs()

    assert jobs[0].company == "Acme Corp"


@patch("jobsearch.sources.lever.requests.get")
def test_fetch_jobs_raises_on_unexpected_payload_shape(mock_get):
    mock_get.return_value = _mock_response({"not": "a list"})
    source = LeverJobSource(company_slug="acme")

    try:
        source.fetch_jobs()
        assert False, "expected JobSourceError"
    except JobSourceError:
        pass


@patch("jobsearch.sources.lever.requests.get")
def test_fetch_jobs_raises_job_source_error_on_network_failure(mock_get):
    mock_get.side_effect = requests.Timeout("timed out")
    source = LeverJobSource(company_slug="acme")

    try:
        source.fetch_jobs()
        assert False, "expected JobSourceError"
    except JobSourceError:
        pass


@patch("jobsearch.sources.lever.requests.get")
def test_safe_fetch_jobs_swallows_errors_and_returns_empty_list(mock_get):
    mock_get.side_effect = requests.Timeout("timed out")
    source = LeverJobSource(company_slug="acme")

    jobs = source.safe_fetch_jobs()

    assert jobs == []
