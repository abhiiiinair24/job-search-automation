from unittest.mock import patch

from jobsearch import cli
from jobsearch.engine import SearchResult
from jobsearch.models import Job, SourceType
from jobsearch.ranking import score_job


def _scored_job(title="AI/ML Engineer", company="Acme"):
    job = Job(
        source=SourceType.GREENHOUSE,
        source_job_id="1",
        company=company,
        title=title,
        location="Remote - US",
        url="https://example.com/1",
        description="RAG, LangChain, PyTorch, Kafka, AWS. 3-5 years.",
    )
    score_job(job)
    return job


@patch("jobsearch.cli.run_search")
def test_main_prints_jobs_and_returns_zero(mock_run_search, capsys):
    job = _scored_job()
    mock_run_search.return_value = SearchResult(
        jobs=[job], total_fetched=1, total_after_filters=1, failed_sources=[]
    )

    exit_code = cli.main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "AI/ML Engineer" in captured.out
    assert "Acme" in captured.out
    assert "Fit score" in captured.out


@patch("jobsearch.cli.run_search")
def test_main_handles_no_results(mock_run_search, capsys):
    mock_run_search.return_value = SearchResult(
        jobs=[], total_fetched=0, total_after_filters=0, failed_sources=[]
    )

    exit_code = cli.main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No matching jobs found" in captured.out


@patch("jobsearch.cli.run_search")
def test_main_reports_failed_sources(mock_run_search, capsys):
    mock_run_search.return_value = SearchResult(
        jobs=[], total_fetched=0, total_after_filters=0, failed_sources=["greenhouse:acme"]
    )

    cli.main([])

    captured = capsys.readouterr()
    assert "greenhouse:acme" in captured.out


@patch("jobsearch.cli.run_search")
def test_main_respects_limit_argument(mock_run_search, capsys):
    jobs = [_scored_job(title=f"Engineer {i}") for i in range(5)]
    mock_run_search.return_value = SearchResult(
        jobs=jobs, total_fetched=5, total_after_filters=5, failed_sources=[]
    )

    cli.main(["--limit", "2", "--top", "1"])

    captured = capsys.readouterr()
    assert "Engineer 0" in captured.out
    assert "Engineer 1" in captured.out
    assert "Engineer 2" not in captured.out
