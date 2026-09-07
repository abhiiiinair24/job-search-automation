from datetime import datetime, timezone

import pytest

from jobsearch.email.formatter import (
    MAX_JOBS_IN_EMAIL,
    TOP_N_HIGHLIGHT,
    format_email_subject,
    format_search_result_email,
)
from jobsearch.engine import SearchResult
from jobsearch.models import Job, SourceType, SponsorshipStatus

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _job(
    job_id="1",
    title="AI/ML Engineer",
    company="Acme",
    location="Buffalo, NY",
    url="https://example.com/apply/1",
    description="",
    fit_score=10.0,
    fit_explanation="matches on: rag, python",
    matched_keywords=None,
    sponsorship_status=SponsorshipStatus.UNKNOWN,
    sponsorship_evidence=None,
    min_experience_years=None,
    max_experience_years=None,
    experience_basis=None,
    experience_matched_tech=None,
    raw_experience_text=None,
    date_updated=NOW,
) -> Job:
    return Job(
        source=SourceType.GREENHOUSE,
        source_job_id=job_id,
        company=company,
        title=title,
        location=location,
        url=url,
        description=description,
        date_updated=date_updated,
        fit_score=fit_score,
        fit_explanation=fit_explanation,
        matched_keywords=matched_keywords or [],
        sponsorship_status=sponsorship_status,
        sponsorship_evidence=sponsorship_evidence,
        min_experience_years=min_experience_years,
        max_experience_years=max_experience_years,
        experience_basis=experience_basis,
        experience_matched_tech=experience_matched_tech,
        raw_experience_text=raw_experience_text,
    )


def _result(jobs, new_jobs=None, already_seen_jobs=None) -> SearchResult:
    return SearchResult(
        jobs=jobs,
        total_fetched=len(jobs),
        total_after_filters=len(jobs),
        failed_sources=[],
        new_jobs=new_jobs if new_jobs is not None else jobs,
        already_seen_jobs=already_seen_jobs or [],
    )


# --- zero-results email -----------------------------------------------------


def test_zero_new_jobs_produces_short_email_no_fabricated_jobs():
    result = _result(jobs=[], new_jobs=[])
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "No new matching jobs were found" in html_out
    assert "<table" not in html_out  # no jobs table at all
    assert "Top" not in html_out  # no "Top N matches" header


def test_zero_new_jobs_subject_line():
    result = _result(jobs=[], new_jobs=[])
    assert format_email_subject(result) == "Job Search Update — no new matches"


def test_nonzero_subject_line_uses_singular_for_one_job():
    job = _job()
    result = _result([job])
    assert format_email_subject(result) == "Job Search Update — 1 new match"


def test_nonzero_subject_line_uses_plural_for_multiple_jobs():
    jobs = [_job(job_id=str(i)) for i in range(3)]
    result = _result(jobs)
    assert format_email_subject(result) == "Job Search Update — 3 new matches"


# --- timestamp + count -------------------------------------------------------


def test_email_includes_search_timestamp():
    result = _result([_job()])
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "2026-09-07 12:00 UTC" in html_out


def test_email_includes_count_of_new_jobs():
    jobs = [_job(job_id=str(i)) for i in range(5)]
    result = _result(jobs)
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "<strong>5</strong> new matching job" in html_out


# --- top-4 highlighting -------------------------------------------------------


def test_top_4_jobs_are_highlighted_with_rank_labels():
    jobs = [_job(job_id=str(i), title=f"Job {i}") for i in range(6)]
    result = _result(jobs)
    html_out = format_search_result_email(result, generated_at=NOW)
    for i in range(4):
        assert f"#{i + 1}: Job {i}" in html_out


def test_top_4_jobs_include_why_it_matches_experience_and_sponsorship_and_emphasize():
    job = _job(
        fit_explanation="title matches target role 'ai/ml engineer'; matches on: rag",
        matched_keywords=["rag", "python"],
        raw_experience_text="3-5 years, overall requirement (parsed from posting)",
        sponsorship_status=SponsorshipStatus.AVAILABLE,
    )
    result = _result([job])
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "Why it&#x27;s a strong match:" in html_out or "Why it's a strong match:" in html_out
    assert "3-5 years, overall requirement" in html_out
    assert "Available" in html_out
    assert "Emphasize: rag, python" in html_out


def test_fewer_than_4_jobs_only_highlights_what_exists():
    jobs = [_job(job_id=str(i), title=f"Job {i}") for i in range(2)]
    result = _result(jobs)
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "Top 2 matches" in html_out
    assert "#3" not in html_out


def test_jobs_beyond_top_4_appear_in_other_matches_section():
    jobs = [_job(job_id=str(i), title=f"Job {i}") for i in range(6)]
    result = _result(jobs)
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "Other strong matches" in html_out
    assert "Job 4" in html_out
    assert "Job 5" in html_out


def test_no_other_matches_section_when_four_or_fewer_jobs():
    jobs = [_job(job_id=str(i), title=f"Job {i}") for i in range(4)]
    result = _result(jobs)
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "Other strong matches" not in html_out


# --- 10-15 cap ---------------------------------------------------------------


def test_email_caps_at_max_jobs_and_notes_the_total():
    jobs = [_job(job_id=str(i), title=f"Job {i}") for i in range(20)]
    result = _result(jobs)
    html_out = format_search_result_email(result, generated_at=NOW)
    for i in range(MAX_JOBS_IN_EMAIL):
        assert f"Job {i}" in html_out
    for i in range(MAX_JOBS_IN_EMAIL, 20):
        assert f"Job {i}" not in html_out
    assert f"showing the top {MAX_JOBS_IN_EMAIL}" in html_out
    assert "<strong>20</strong> new matching job" in html_out  # true count, not capped


def test_email_does_not_note_cap_when_under_the_limit():
    jobs = [_job(job_id=str(i)) for i in range(3)]
    result = _result(jobs)
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "showing the top" not in html_out


# --- sponsorship rendering ----------------------------------------------------


@pytest.mark.parametrize(
    "status,evidence,expected_text",
    [
        (SponsorshipStatus.AVAILABLE, "we sponsor h1b", "Available"),
        (SponsorshipStatus.NOT_AVAILABLE, "no visa sponsorship", "Not available"),
        (SponsorshipStatus.UNKNOWN, None, "Unknown / not mentioned"),
    ],
)
def test_sponsorship_status_rendering(status, evidence, expected_text):
    job = _job(sponsorship_status=status, sponsorship_evidence=evidence)
    result = _result([job])
    html_out = format_search_result_email(result, generated_at=NOW)
    assert expected_text in html_out
    if evidence:
        assert evidence in html_out


def test_sponsorship_concern_shown_for_not_available():
    job = _job(sponsorship_status=SponsorshipStatus.NOT_AVAILABLE)
    result = _result([job])
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "sponsorship is not available" in html_out.lower()


def test_sponsorship_concern_shown_for_unknown():
    job = _job(sponsorship_status=SponsorshipStatus.UNKNOWN)
    result = _result([job])
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "confirm directly" in html_out.lower()


def test_no_sponsorship_concern_when_available():
    job = _job(
        sponsorship_status=SponsorshipStatus.AVAILABLE,
        min_experience_years=3,
        experience_basis="overall",
    )
    result = _result([job])
    html_out = format_search_result_email(result, generated_at=NOW, candidate_years=4.0)
    assert "Concern" not in html_out


# --- experience concern -------------------------------------------------------


def test_experience_concern_when_unstated():
    job = _job(min_experience_years=None, raw_experience_text=None)
    result = _result([job])
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "No experience requirement was stated" in html_out


def test_experience_concern_when_tech_specific_basis():
    job = _job(
        min_experience_years=5,
        experience_basis="tech_specific",
        experience_matched_tech="python",
        raw_experience_text="5-? years, tech-specific (python) (parsed from posting)",
    )
    result = _result([job])
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "only tied to python experience" in html_out


def test_experience_concern_when_above_candidate_years():
    job = _job(
        min_experience_years=8,
        experience_basis="overall",
        raw_experience_text="8-? years, overall requirement (parsed from posting)",
    )
    result = _result([job])
    html_out = format_search_result_email(result, generated_at=NOW, candidate_years=4.0)
    assert "above your ~4 years" in html_out


def test_no_experience_concern_when_within_candidate_years():
    job = _job(
        min_experience_years=3,
        experience_basis="overall",
        raw_experience_text="3-5 years, overall requirement (parsed from posting)",
        sponsorship_status=SponsorshipStatus.AVAILABLE,
    )
    result = _result([job])
    html_out = format_search_result_email(result, generated_at=NOW, candidate_years=4.0)
    assert "Concern" not in html_out


def test_no_experience_concern_computed_when_candidate_years_not_provided():
    job = _job(
        min_experience_years=8,
        experience_basis="overall",
        raw_experience_text="8-? years, overall requirement (parsed from posting)",
    )
    result = _result([job])
    # candidate_years omitted entirely - shouldn't crash, shouldn't claim a mismatch.
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "above your" not in html_out


# --- application URLs ---------------------------------------------------------


def test_application_url_rendered_as_link():
    job = _job(url="https://boards.greenhouse.io/acme/jobs/123")
    result = _result([job])
    html_out = format_search_result_email(result, generated_at=NOW)
    assert 'href="https://boards.greenhouse.io/acme/jobs/123"' in html_out
    assert "Apply here" in html_out


def test_application_url_in_remaining_section_too():
    jobs = [_job(job_id=str(i), url=f"https://example.com/job/{i}") for i in range(5)]
    result = _result(jobs)
    html_out = format_search_result_email(result, generated_at=NOW)
    assert 'href="https://example.com/job/4"' in html_out


def test_application_url_with_query_params_is_escaped_safely():
    job = _job(url="https://example.com/apply?ref=1&utm=2")
    result = _result([job])
    html_out = format_search_result_email(result, generated_at=NOW)
    assert 'href="https://example.com/apply?ref=1&amp;utm=2"' in html_out


# --- HTML/special character escaping -----------------------------------------


def test_html_special_characters_are_escaped_in_title_and_company():
    job = _job(
        title="<script>alert('x')</script>",
        company='Acme "Corp" & Co <Ltd>',
    )
    result = _result([job])
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "<script>alert" not in html_out
    assert "&lt;script&gt;" in html_out
    assert "&amp;" in html_out
    assert "&quot;Corp&quot;" in html_out or "&#x27;" in html_out


def test_html_special_characters_escaped_in_fit_explanation_and_location():
    job = _job(
        location='New York, NY <remote optional>',
        fit_explanation="matches on: c++ & c#, \"backend\"",
    )
    result = _result([job])
    html_out = format_search_result_email(result, generated_at=NOW)
    assert "<remote optional>" not in html_out
    assert "&lt;remote optional&gt;" in html_out
    assert "&amp;" in html_out


def test_no_unescaped_angle_brackets_from_job_data_leak_into_markup():
    job = _job(title="Engineer <VIP>", company="Acme")
    result = _result([job])
    html_out = format_search_result_email(result, generated_at=NOW)
    # The only literal "<" characters should be from our own template tags
    # (like <html>, <div>, <p>...), never from job data.
    assert "<VIP>" not in html_out
