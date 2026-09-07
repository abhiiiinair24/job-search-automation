from datetime import datetime, timedelta, timezone

from jobsearch.filters.recency import is_recent


def test_is_recent_true_for_job_updated_today(make_job):
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    job = make_job(date_updated=now)
    assert is_recent(job, reference_time=now, max_age_days=4) is True


def test_is_recent_true_at_exact_boundary(make_job):
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    job = make_job(date_updated=now - timedelta(days=4))
    assert is_recent(job, reference_time=now, max_age_days=4) is True


def test_is_recent_false_just_past_boundary(make_job):
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    job = make_job(date_updated=now - timedelta(days=4, minutes=1))
    assert is_recent(job, reference_time=now, max_age_days=4) is False


def test_is_recent_false_for_old_job(make_job):
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    job = make_job(date_updated=now - timedelta(days=30))
    assert is_recent(job, reference_time=now, max_age_days=4) is False


def test_is_recent_false_when_no_date_available(make_job):
    job = make_job(date_updated=None)
    job.date_posted = None
    job.date_updated = None
    assert is_recent(job, reference_time=datetime.now(timezone.utc)) is False


def test_is_recent_handles_naive_datetimes(make_job):
    now = datetime(2026, 9, 7)  # naive
    job = make_job(date_updated=datetime(2026, 9, 6))  # naive, 1 day earlier
    assert is_recent(job, reference_time=now, max_age_days=4) is True
