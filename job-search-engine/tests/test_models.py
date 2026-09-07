from datetime import datetime, timezone

from jobsearch.models import Job, SourceType


def test_stable_id_uses_source_and_native_id(make_job):
    job = make_job(source=SourceType.GREENHOUSE, source_job_id="42")
    assert job.stable_id == "greenhouse:42"


def test_stable_id_differs_across_sources_with_same_native_id(make_job):
    gh_job = make_job(source=SourceType.GREENHOUSE, source_job_id="42")
    lever_job = make_job(source=SourceType.LEVER, source_job_id="42")
    assert gh_job.stable_id != lever_job.stable_id


def test_stable_id_falls_back_to_hash_when_no_native_id():
    job = Job(
        source=SourceType.GREENHOUSE,
        source_job_id="",
        company="Acme",
        title="Backend Engineer",
        location="Remote - US",
        url="https://example.com",
        description="",
    )
    assert job.stable_id.startswith("fallback:")


def test_fallback_stable_id_is_deterministic_for_same_fields():
    kwargs = dict(
        source=SourceType.LEVER,
        source_job_id="",
        company="Acme",
        title="Backend Engineer",
        location="Remote - US",
        url="https://example.com",
        description="",
    )
    job_a = Job(**kwargs)
    job_b = Job(**kwargs)
    assert job_a.stable_id == job_b.stable_id


def test_most_recent_date_prefers_updated_over_posted():
    posted = datetime(2026, 1, 1, tzinfo=timezone.utc)
    updated = datetime(2026, 2, 1, tzinfo=timezone.utc)
    job = Job(
        source=SourceType.GREENHOUSE,
        source_job_id="1",
        company="Acme",
        title="Engineer",
        location="Remote",
        url="https://example.com",
        description="",
        date_posted=posted,
        date_updated=updated,
    )
    assert job.most_recent_date == updated


def test_most_recent_date_falls_back_to_posted_when_no_updated():
    posted = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job = Job(
        source=SourceType.GREENHOUSE,
        source_job_id="1",
        company="Acme",
        title="Engineer",
        location="Remote",
        url="https://example.com",
        description="",
        date_posted=posted,
        date_updated=None,
    )
    assert job.most_recent_date == posted
