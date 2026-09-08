from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import patch

import pytest

from jobsearch.config import Config
from jobsearch.email.config import EmailConfigError
from jobsearch.email.gmail_sender import GmailSendError
from jobsearch.models import Job, SourceType
from jobsearch.orchestrator import OrchestrationError, run_scheduled_search
from jobsearch.seen_store import InMemorySeenJobStore, JsonFileSeenJobStore
from jobsearch.sources.base import JobSource, JobSourceError

NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)


class FakeSource(JobSource):
    """A JobSource stub - no network calls, fully deterministic."""

    def __init__(self, name: str, jobs: List[Job] = None, should_fail: bool = False):
        self.name = name
        self._jobs = jobs or []
        self._should_fail = should_fail

    def fetch_jobs(self) -> List[Job]:
        if self._should_fail:
            raise JobSourceError("simulated source failure")
        return self._jobs


def _job(job_id, title="AI/ML Engineer", description="RAG, PyTorch, Kafka, AWS. 3-5 years.", days_ago=1):
    return Job(
        source=SourceType.GREENHOUSE,
        source_job_id=job_id,
        company="Acme",
        title=title,
        location="Buffalo, NY",
        url=f"https://example.com/{job_id}",
        description=description,
        date_posted=NOW - timedelta(days=days_ago),
        date_updated=NOW - timedelta(days=days_ago),
    )


def _mock_send_success(monkeypatch_target="jobsearch.orchestrator.send_search_result_email"):
    return patch(monkeypatch_target, return_value={"id": "msg-123"})


# --- 1. New jobs are emailed -------------------------------------------------


def test_new_jobs_are_emailed():
    job = _job("1")
    seen_store = InMemorySeenJobStore()

    with _mock_send_success() as mock_send:
        run_scheduled_search(
            config=Config(), seen_store=seen_store, sources=[FakeSource("fake", [job])]
        )

    mock_send.assert_called_once()
    (sent_result,), _ = mock_send.call_args
    assert len(sent_result.new_jobs) == 1
    assert sent_result.new_jobs[0].source_job_id == "1"


# --- 2. Already-seen jobs are not emailed again ------------------------------


def test_already_seen_jobs_are_not_emailed_again():
    job = _job("1")
    seen_store = InMemorySeenJobStore(initial_seen=[job.stable_id])

    with _mock_send_success() as mock_send:
        run_scheduled_search(
            config=Config(), seen_store=seen_store, sources=[FakeSource("fake", [job])]
        )

    (sent_result,), _ = mock_send.call_args
    assert sent_result.new_jobs == []
    assert len(sent_result.already_seen_jobs) == 1


# --- 3. Jobs marked seen ONLY after successful delivery ----------------------


def test_jobs_marked_seen_only_after_successful_send():
    job = _job("1")
    seen_store = InMemorySeenJobStore()
    assert job.stable_id not in seen_store.get_seen_ids()

    with _mock_send_success():
        outcome = run_scheduled_search(
            config=Config(), seen_store=seen_store, sources=[FakeSource("fake", [job])]
        )

    assert outcome.marked_seen_count == 1
    assert job.stable_id in seen_store.get_seen_ids()


# --- 4. Jobs NOT marked seen if Gmail fails ----------------------------------


def test_jobs_not_marked_seen_when_gmail_send_fails():
    job = _job("1")
    seen_store = InMemorySeenJobStore()

    with patch(
        "jobsearch.orchestrator.send_search_result_email",
        side_effect=GmailSendError("simulated failure"),
    ):
        with pytest.raises(OrchestrationError):
            run_scheduled_search(
                config=Config(), seen_store=seen_store, sources=[FakeSource("fake", [job])]
            )

    assert seen_store.get_seen_ids() == set()


def test_jobs_not_marked_seen_when_email_config_invalid():
    job = _job("1")
    seen_store = InMemorySeenJobStore()

    with patch(
        "jobsearch.orchestrator.send_search_result_email",
        side_effect=EmailConfigError("JOBSEARCH_RECIPIENT_EMAIL is not set"),
    ):
        with pytest.raises(OrchestrationError):
            run_scheduled_search(
                config=Config(), seen_store=seen_store, sources=[FakeSource("fake", [job])]
            )

    assert seen_store.get_seen_ids() == set()


# --- 5. All 10-15 jobs are included in the email -----------------------------


def test_all_new_jobs_passed_through_for_emailing_not_just_top_4():
    jobs = [_job(str(i), title=f"Job {i}") for i in range(12)]
    seen_store = InMemorySeenJobStore()

    with _mock_send_success() as mock_send:
        run_scheduled_search(
            config=Config(), seen_store=seen_store, sources=[FakeSource("fake", jobs)]
        )

    (sent_result,), _ = mock_send.call_args
    # The orchestrator must hand the FULL new-jobs list to the email layer -
    # capping/highlighting is the formatter's job, not the orchestrator's.
    assert len(sent_result.new_jobs) == 12


def test_all_new_jobs_actually_appear_in_rendered_email_body():
    # End-to-end through the real formatter (only the Gmail network call is
    # mocked) to confirm all 12 jobs genuinely appear in the HTML, not just
    # passed through as data.
    jobs = [_job(str(i), title=f"Unique Job Title {i}") for i in range(12)]
    seen_store = InMemorySeenJobStore()

    with patch("jobsearch.email.gmail_sender.send_email") as mock_send_email:
        mock_send_email.return_value = {"id": "msg-1"}
        with patch.dict(
            "os.environ",
            {"JOBSEARCH_RECIPIENT_EMAIL": "someone@example.com"},
        ):
            run_scheduled_search(
                config=Config(), seen_store=seen_store, sources=[FakeSource("fake", jobs)]
            )

    _, kwargs = mock_send_email.call_args
    html_body = kwargs["html_body"]
    for i in range(12):
        assert f"Unique Job Title {i}" in html_body


# --- 6. Top 4 are highlighted -------------------------------------------------


def test_top_4_highlighted_in_rendered_email():
    jobs = [_job(str(i), title=f"Job {i}") for i in range(6)]
    seen_store = InMemorySeenJobStore()

    with patch("jobsearch.email.gmail_sender.send_email") as mock_send_email:
        mock_send_email.return_value = {"id": "msg-1"}
        with patch.dict("os.environ", {"JOBSEARCH_RECIPIENT_EMAIL": "someone@example.com"}):
            run_scheduled_search(
                config=Config(), seen_store=seen_store, sources=[FakeSource("fake", jobs)]
            )

    html_body = mock_send_email.call_args.kwargs["html_body"]
    assert "Top 4 matches" in html_body
    assert "Other strong matches" in html_body


# --- 7. Zero-new-jobs behavior -------------------------------------------------


def test_zero_new_jobs_still_sends_short_email_and_marks_nothing_seen():
    seen_store = InMemorySeenJobStore()

    with _mock_send_success() as mock_send:
        outcome = run_scheduled_search(
            config=Config(), seen_store=seen_store, sources=[FakeSource("fake", [])]
        )

    mock_send.assert_called_once()
    (sent_result,), _ = mock_send.call_args
    assert sent_result.new_jobs == []
    assert outcome.marked_seen_count == 0
    assert seen_store.get_seen_ids() == set()


def test_zero_new_jobs_when_all_fetched_jobs_already_seen():
    job = _job("1")
    seen_store = InMemorySeenJobStore(initial_seen=[job.stable_id])

    with _mock_send_success() as mock_send:
        outcome = run_scheduled_search(
            config=Config(), seen_store=seen_store, sources=[FakeSource("fake", [job])]
        )

    (sent_result,), _ = mock_send.call_args
    assert sent_result.new_jobs == []
    assert outcome.marked_seen_count == 0
    # The already-seen job must not be re-marked or duplicated.
    assert seen_store.get_seen_ids() == {job.stable_id}


# --- 8. Persistent seen state survives a subsequent run ----------------------


def test_persistent_seen_state_survives_subsequent_run(tmp_path):
    store_path = tmp_path / "seen_jobs.json"
    job_a = _job("a", title="Job A")
    job_b = _job("b", title="Job B")

    config = Config(seen_store_path=str(store_path))

    # Run 1: only job A exists.
    with _mock_send_success() as mock_send:
        outcome1 = run_scheduled_search(
            config=config,
            seen_store=JsonFileSeenJobStore(path=store_path),
            sources=[FakeSource("fake", [job_a])],
        )
    assert outcome1.marked_seen_count == 1
    assert store_path.exists()

    # Run 2: a FRESH store instance pointed at the same file (simulating a
    # new, ephemeral CI runner) - job A should now be seen, job B is new.
    fresh_store = JsonFileSeenJobStore(path=store_path)
    with _mock_send_success() as mock_send:
        outcome2 = run_scheduled_search(
            config=config, seen_store=fresh_store, sources=[FakeSource("fake", [job_a, job_b])]
        )

    (sent_result,), _ = mock_send.call_args
    assert {j.title for j in sent_result.new_jobs} == {"Job B"}
    assert outcome2.marked_seen_count == 1

    # Confirm both are now persisted for a third run.
    final_store = JsonFileSeenJobStore(path=store_path)
    assert final_store.get_seen_ids() == {job_a.stable_id, job_b.stable_id}


# --- one failed source must not crash the run --------------------------------


def test_one_failed_source_does_not_crash_the_run():
    good_job = _job("1")
    seen_store = InMemorySeenJobStore()
    sources = [FakeSource("broken", should_fail=True), FakeSource("good", [good_job])]

    with _mock_send_success() as mock_send:
        outcome = run_scheduled_search(config=Config(), seen_store=seen_store, sources=sources)

    assert outcome.marked_seen_count == 1
    (sent_result,), _ = mock_send.call_args
    assert len(sent_result.new_jobs) == 1
    assert "broken" in sent_result.failed_sources


# --- 10. Missing required secrets/configuration fails clearly ----------------


def test_missing_email_config_fails_clearly_without_calling_gmail(monkeypatch):
    monkeypatch.delenv("JOBSEARCH_RECIPIENT_EMAIL", raising=False)
    job = _job("1")
    seen_store = InMemorySeenJobStore()

    with patch("jobsearch.email.gmail_sender.send_email") as mock_send_email:
        with pytest.raises(OrchestrationError) as exc_info:
            run_scheduled_search(
                config=Config(), seen_store=seen_store, sources=[FakeSource("fake", [job])]
            )

    assert "JOBSEARCH_RECIPIENT_EMAIL" in str(exc_info.value)
    # Must fail before ever attempting a real Gmail network call.
    mock_send_email.assert_not_called()
    assert seen_store.get_seen_ids() == set()


def test_missing_gmail_credentials_fails_clearly(monkeypatch):
    monkeypatch.setenv("JOBSEARCH_RECIPIENT_EMAIL", "someone@example.com")
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN", raising=False)

    job = _job("1")
    seen_store = InMemorySeenJobStore()

    with patch("googleapiclient.discovery.build") as mock_build:
        with pytest.raises(OrchestrationError) as exc_info:
            run_scheduled_search(
                config=Config(), seen_store=seen_store, sources=[FakeSource("fake", [job])]
            )

    assert "GMAIL_CLIENT_ID" in str(exc_info.value) or "Gmail" in str(exc_info.value)
    mock_build.assert_not_called()
    assert seen_store.get_seen_ids() == set()
