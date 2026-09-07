from jobsearch.dedup import deduplicate_jobs
from jobsearch.models import SourceType


def test_deduplicate_jobs_removes_exact_duplicates(make_job):
    job_a = make_job(source=SourceType.GREENHOUSE, source_job_id="1")
    job_b = make_job(source=SourceType.GREENHOUSE, source_job_id="1")
    result = deduplicate_jobs([job_a, job_b])
    assert len(result) == 1
    assert result[0] is job_a  # keeps first occurrence


def test_deduplicate_jobs_keeps_distinct_ids(make_job):
    job_a = make_job(source=SourceType.GREENHOUSE, source_job_id="1")
    job_b = make_job(source=SourceType.GREENHOUSE, source_job_id="2")
    result = deduplicate_jobs([job_a, job_b])
    assert len(result) == 2


def test_deduplicate_jobs_treats_different_sources_as_distinct(make_job):
    job_a = make_job(source=SourceType.GREENHOUSE, source_job_id="1")
    job_b = make_job(source=SourceType.LEVER, source_job_id="1")
    result = deduplicate_jobs([job_a, job_b])
    assert len(result) == 2


def test_deduplicate_jobs_empty_list():
    assert deduplicate_jobs([]) == []
