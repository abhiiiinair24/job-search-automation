from unittest.mock import Mock, patch

import requests

from jobsearch.models import SourceType
from jobsearch.sources.base import JobSourceError
from jobsearch.sources.greenhouse import GreenhouseJobSource

SAMPLE_PAYLOAD = {
    "jobs": [
        {
            "id": 111,
            "title": "Backend Software Engineer",
            "location": {"name": "Remote - US"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/111",
            "content": "<p>3-5 years of experience with Java and Kafka.</p>",
            "updated_at": "2026-09-06T12:00:00-05:00",
        },
        {
            # Malformed: missing "id" -> should be skipped, not crash the whole fetch.
            "title": "Broken Posting",
            "location": {"name": "Remote"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/broken",
            "content": "",
            "updated_at": None,
        },
    ]
}


def _mock_response(json_data, status_code=200, raise_for_status_error=None):
    mock_resp = Mock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    if raise_for_status_error:
        mock_resp.raise_for_status.side_effect = raise_for_status_error
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


@patch("jobsearch.sources.greenhouse.requests.get")
def test_fetch_jobs_parses_valid_postings(mock_get):
    mock_get.return_value = _mock_response(SAMPLE_PAYLOAD)
    source = GreenhouseJobSource(board_token="acme")

    jobs = source.fetch_jobs()

    # One job is malformed (missing id) and should be skipped, not crash the run.
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == SourceType.GREENHOUSE
    assert job.source_job_id == "111"
    assert job.company == "acme"
    assert job.title == "Backend Software Engineer"
    assert job.location == "Remote - US"
    assert job.is_remote is True
    assert "Kafka" in job.description
    assert job.date_updated is not None


@patch("jobsearch.sources.greenhouse.requests.get")
def test_fetch_jobs_uses_company_name_override(mock_get):
    mock_get.return_value = _mock_response(SAMPLE_PAYLOAD)
    source = GreenhouseJobSource(board_token="acme", company_name="Acme Corp")

    jobs = source.fetch_jobs()

    assert jobs[0].company == "Acme Corp"


@patch("jobsearch.sources.greenhouse.requests.get")
def test_fetch_jobs_raises_job_source_error_on_network_failure(mock_get):
    mock_get.side_effect = requests.ConnectionError("boom")
    source = GreenhouseJobSource(board_token="acme")

    try:
        source.fetch_jobs()
        assert False, "expected JobSourceError"
    except JobSourceError:
        pass


@patch("jobsearch.sources.greenhouse.requests.get")
def test_fetch_jobs_raises_job_source_error_on_http_error(mock_get):
    mock_get.return_value = _mock_response(
        {}, status_code=500, raise_for_status_error=requests.HTTPError("server error")
    )
    source = GreenhouseJobSource(board_token="acme")

    try:
        source.fetch_jobs()
        assert False, "expected JobSourceError"
    except JobSourceError:
        pass


@patch("jobsearch.sources.greenhouse.requests.get")
def test_safe_fetch_jobs_swallows_errors_and_returns_empty_list(mock_get):
    mock_get.side_effect = requests.ConnectionError("boom")
    source = GreenhouseJobSource(board_token="acme")

    jobs = source.safe_fetch_jobs()

    assert jobs == []


@patch("jobsearch.sources.greenhouse.requests.get")
def test_fetch_jobs_empty_jobs_list(mock_get):
    mock_get.return_value = _mock_response({"jobs": []})
    source = GreenhouseJobSource(board_token="acme")

    jobs = source.fetch_jobs()

    assert jobs == []
