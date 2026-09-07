import pytest

from jobsearch.filters.experience import (
    annotate_experience,
    extract_experience_requirement,
    passes_experience_filter,
)


@pytest.mark.parametrize(
    "text,expected_min,expected_max",
    [
        ("We need 3-5 years of experience with Java.", 3, 5),
        ("3 to 5 years of backend experience required.", 3, 5),
        ("5+ years of experience with distributed systems.", 5, None),
        ("At least 6 years of experience needed.", 6, None),
        ("Minimum of 2 years experience with Python.", 2, None),
        ("2 years of experience with AWS.", 2, 2),
        ("No years mentioned here at all.", None, None),
    ],
)
def test_extract_experience_requirement_patterns(text, expected_min, expected_max):
    req = extract_experience_requirement(text)
    assert req.min_years == expected_min
    assert req.max_years == expected_max


def test_extract_experience_requirement_detects_new_grad_signal():
    req = extract_experience_requirement("This is a New Grad role, entry-level friendly.")
    assert req.is_new_grad_signal is True


def test_extract_experience_requirement_no_new_grad_signal_for_normal_posting():
    req = extract_experience_requirement("3-5 years of experience with Kafka required.")
    assert req.is_new_grad_signal is False


def test_annotate_experience_sets_fields_on_job(make_job):
    job = make_job(description="Looking for someone with 3-5 years of experience.")
    annotate_experience(job)
    assert job.min_experience_years == 3
    assert job.max_experience_years == 5
    assert "3-5 years" in job.raw_experience_text


def test_passes_experience_filter_excludes_hard_minimum(make_job):
    job = make_job(description="Requires at least 7 years of experience.")
    annotate_experience(job)
    assert passes_experience_filter(job, hard_exclude_years=6) is False


def test_passes_experience_filter_allows_boundary_below_exclude(make_job):
    job = make_job(description="Requires 5+ years of experience.")
    annotate_experience(job)
    assert passes_experience_filter(job, hard_exclude_years=6) is True


def test_passes_experience_filter_allows_unspecified_requirement(make_job):
    job = make_job(description="No experience requirement mentioned.")
    annotate_experience(job)
    assert passes_experience_filter(job, hard_exclude_years=6) is True


def test_passes_experience_filter_allows_new_grad_role_not_excluded(make_job):
    # New-grad roles are deprioritized in ranking, not hard-excluded here.
    job = make_job(description="New Grad Software Engineer role, entry level.")
    annotate_experience(job)
    assert passes_experience_filter(job, hard_exclude_years=6) is True


# --- Overall vs. tech-specific classification -------------------------------


@pytest.mark.parametrize(
    "text,expected_min,expected_max,expected_basis",
    [
        ("3+ years of software engineering experience", 3, None, "overall"),
        ("5+ years of experience in software development", 5, None, "overall"),
        (
            "3+ years of Python experience and 7+ years of engineering experience",
            7,
            None,
            "overall",
        ),
        ("3+ years of experience with Python", 3, None, "tech_specific"),
    ],
)
def test_extract_experience_requirement_overall_vs_tech_specific(
    text, expected_min, expected_max, expected_basis
):
    req = extract_experience_requirement(text)
    assert req.min_years == expected_min
    assert req.max_years == expected_max
    assert req.basis == expected_basis


def test_overall_requirement_wins_even_when_tech_mention_is_larger():
    # The tech-specific number (8) is larger than the overall one (4), but
    # the overall requirement is still what gates candidacy.
    text = "8+ years of Kafka experience and 4+ years of overall software engineering experience"
    req = extract_experience_requirement(text)
    assert req.min_years == 4
    assert req.basis == "overall"


def test_tech_specific_mention_used_as_fallback_when_no_overall_exists():
    text = "3+ years of experience with Python"
    req = extract_experience_requirement(text)
    assert req.min_years == 3
    assert req.basis == "tech_specific"
    assert req.matched_tech == "python"


def test_multiple_tech_specific_mentions_take_the_strictest():
    text = "2+ years of experience with Java and 5+ years of experience with Kafka"
    req = extract_experience_requirement(text)
    # No overall mention exists, so we fall back to the strictest
    # tech-specific requirement found.
    assert req.min_years == 5
    assert req.basis == "tech_specific"
    assert req.matched_tech == "kafka"


def test_tech_mention_does_not_leak_into_neighboring_overall_clause():
    text = "3+ years of Python experience and 7+ years of engineering experience"
    req = extract_experience_requirement(text)
    # Confirm the *overall* clause won, not merely that 7 > 3 - this
    # verifies clause-scoped context, not just "take the max number".
    assert req.basis == "overall"
    assert req.matched_tech is None


def test_annotate_experience_records_basis_and_matched_tech(make_job):
    job = make_job(description="3+ years of experience with Python")
    annotate_experience(job)
    assert job.experience_basis == "tech_specific"
    assert job.experience_matched_tech == "python"
    assert "python" in job.raw_experience_text.lower()


def test_annotate_experience_records_overall_basis(make_job):
    job = make_job(
        description="3+ years of Python experience and 7+ years of engineering experience"
    )
    annotate_experience(job)
    assert job.min_experience_years == 7
    assert job.experience_basis == "overall"
