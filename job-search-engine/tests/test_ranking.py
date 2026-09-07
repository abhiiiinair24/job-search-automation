from jobsearch.filters.experience import annotate_experience
from jobsearch.filters.sponsorship import annotate_sponsorship
from jobsearch.models import SponsorshipStatus
from jobsearch.profile import CandidateProfile, default_profile
from jobsearch.ranking import RankingWeights, rank_jobs, score_job


def test_score_job_rewards_matching_skills(make_job):
    strong = make_job(
        title="AI/ML Engineer",
        description="You'll build RAG pipelines with LangChain, PyTorch, and Kafka on AWS.",
    )
    weak = make_job(
        title="Sales Associate",
        description="You will sell shoes at our retail store.",
    )
    score_job(strong)
    score_job(weak)
    assert strong.fit_score > weak.fit_score


def test_score_job_penalizes_new_grad_postings(make_job):
    job = make_job(
        title="Software Engineer, New Grad",
        description="New Grad Software Engineer role. Entry level. Java, AWS.",
    )
    annotate_experience(job)
    baseline = make_job(
        title="Software Engineer",
        description="Software Engineer role. Java, AWS.",
    )
    annotate_experience(baseline)

    score_job(job)
    score_job(baseline)
    assert job.fit_score < baseline.fit_score


def test_score_job_penalizes_sponsorship_not_available(make_job):
    job = make_job(description="We do not provide visa sponsorship. Java, AWS, Kafka.")
    annotate_sponsorship(job)
    unknown_job = make_job(description="Java, AWS, Kafka.")
    annotate_sponsorship(unknown_job)

    score_job(job)
    score_job(unknown_job)
    assert job.sponsorship_status == SponsorshipStatus.NOT_AVAILABLE
    assert job.fit_score < unknown_job.fit_score


def test_score_job_rewards_sponsorship_available(make_job):
    job = make_job(description="Visa sponsorship is available. Java, AWS, Kafka.")
    annotate_sponsorship(job)
    unknown_job = make_job(description="Java, AWS, Kafka.")
    annotate_sponsorship(unknown_job)

    score_job(job)
    score_job(unknown_job)
    assert job.fit_score > unknown_job.fit_score


def test_score_job_penalizes_experience_above_candidate_level(make_job):
    job = make_job(description="Requires 8 years of experience. Java, AWS.")
    annotate_experience(job)
    weights = RankingWeights(profile=default_profile(years_of_experience=4.0))
    score_job(job, weights)

    baseline = make_job(description="Requires 4 years of experience. Java, AWS.")
    annotate_experience(baseline)
    score_job(baseline, weights)

    assert job.fit_score < baseline.fit_score


def test_rank_jobs_sorts_best_first(make_job):
    strong = make_job(title="AI/ML Engineer", description="RAG, LangChain, PyTorch, Kafka, AWS")
    weak = make_job(title="Sales Associate", description="Sell shoes")
    ranked = rank_jobs([weak, strong])
    assert ranked[0] is strong
    assert ranked[1] is weak


def test_score_job_records_matched_keywords(make_job):
    job = make_job(title="Backend Engineer", description="Kafka, PostgreSQL, AWS, Docker")
    score_job(job)
    assert "kafka" in job.matched_keywords
    assert "aws" in job.matched_keywords


# --- Ranking consumes the injected profile, not hard-coded data -----------


def test_score_job_uses_injected_profile_skills_not_defaults(make_job):
    custom_profile = CandidateProfile(
        years_of_experience=4.0,
        skills={"rust": 5.0},
        target_roles={},
        domain_experience=[],
        projects=[],
    )
    weights = RankingWeights(profile=custom_profile)

    rust_job = make_job(title="Backend Engineer", description="We use Rust extensively.")
    java_job = make_job(title="Backend Engineer", description="We use Java extensively.")

    score_job(rust_job, weights)
    score_job(java_job, weights)

    # Only "rust" is in this custom profile's skills, so it should score
    # higher than a posting matching skills the default profile has but
    # this custom profile does not.
    assert rust_job.fit_score > java_job.fit_score
    assert "rust" in rust_job.matched_keywords


def test_score_job_uses_injected_profile_target_roles(make_job):
    custom_profile = CandidateProfile(
        years_of_experience=4.0,
        skills={},
        target_roles={"data engineer": 5.0},
        domain_experience=[],
        projects=[],
    )
    weights = RankingWeights(profile=custom_profile)

    matching_title = make_job(title="Data Engineer", description="")
    non_matching_title = make_job(title="Marketing Manager", description="")

    score_job(matching_title, weights)
    score_job(non_matching_title, weights)

    assert matching_title.fit_score > non_matching_title.fit_score
    assert "data engineer" in matching_title.fit_explanation


def test_score_job_rewards_domain_experience_match(make_job):
    custom_profile = CandidateProfile(
        years_of_experience=4.0,
        skills={},
        target_roles={},
        domain_experience=["financial payments systems"],
        projects=[],
    )
    weights = RankingWeights(profile=custom_profile)

    payments_job = make_job(
        title="Software Engineer",
        description="You'll work on our financial payments systems team.",
    )
    other_job = make_job(title="Software Engineer", description="You'll work on our website.")

    score_job(payments_job, weights)
    score_job(other_job, weights)

    assert payments_job.fit_score > other_job.fit_score


def test_ranking_weights_candidate_years_reflects_profile():
    weights = RankingWeights(profile=default_profile(years_of_experience=4.0))
    assert weights.candidate_years == 4.0


# --- Regression: word-boundary matching (no more substring false positives) --


def test_score_job_does_not_match_rag_inside_average(make_job):
    # Reproduces a real false positive seen in production: "rag" matching
    # inside "average" on a posting with nothing to do with RAG/LLMs.
    job = make_job(
        title="Backend Engineer, Credit Coverage",
        description="You'll compute the average transaction volume across our systems.",
    )
    score_job(job)
    assert "rag" not in job.matched_keywords


def test_score_job_does_not_match_rag_inside_storage_or_leverage(make_job):
    job = make_job(
        title="Technical Solutions Engineer",
        description="You'll leverage our cloud storage systems to help customers.",
    )
    score_job(job)
    assert "rag" not in job.matched_keywords


def test_score_job_still_matches_real_rag_mentions(make_job):
    job = make_job(
        title="AI/ML Engineer",
        description="You'll build RAG pipelines with LangChain and PyTorch.",
    )
    score_job(job)
    assert "rag" in job.matched_keywords


def test_score_job_does_not_match_sql_inside_mysql(make_job):
    profile = CandidateProfile(
        years_of_experience=4.0,
        skills={"sql": 2.0, "mysql": 1.0},
        target_roles={},
        domain_experience=[],
        projects=[],
    )
    weights = RankingWeights(profile=profile)
    job = make_job(description="We use MySQL as our primary datastore.")
    score_job(job, weights)
    assert "sql" not in job.matched_keywords
    assert "mysql" in job.matched_keywords


# --- Preferred-location prioritization (e.g. Buffalo, NY) -------------------


def test_score_job_adds_bonus_for_preferred_location(make_job):
    profile = CandidateProfile(
        years_of_experience=4.0,
        skills={"java": 2.0},
        target_roles={},
        domain_experience=[],
        projects=[],
        preferred_locations=["buffalo"],
    )
    weights = RankingWeights(profile=profile)

    buffalo_job = make_job(location="Buffalo, NY", description="Java role.")
    other_job = make_job(location="Austin, TX", description="Java role.")

    score_job(buffalo_job, weights)
    score_job(other_job, weights)

    assert buffalo_job.fit_score > other_job.fit_score
    assert "preferred location" in buffalo_job.fit_explanation.lower()


def test_score_job_no_bonus_when_location_does_not_match(make_job):
    profile = CandidateProfile(
        years_of_experience=4.0,
        skills={},
        target_roles={},
        domain_experience=[],
        projects=[],
        preferred_locations=["buffalo"],
    )
    weights = RankingWeights(profile=profile)
    job = make_job(location="Austin, TX", description="")
    score_job(job, weights)
    assert "preferred location" not in job.fit_explanation.lower()


def test_rank_jobs_puts_preferred_location_first_even_with_lower_fit_score(make_job):
    profile = CandidateProfile(
        years_of_experience=4.0,
        skills={
            "python": 2.0, "java": 2.0, "kafka": 2.0, "aws": 2.0, "kubernetes": 2.0,
            "docker": 2.0, "terraform": 2.0, "rag": 2.5, "langchain": 2.5,
        },
        target_roles={"ai/ml engineer": 3.0},
        domain_experience=[],
        projects=[],
        preferred_locations=["buffalo"],
    )
    weights = RankingWeights(profile=profile)

    # A strong-fit job located elsewhere...
    strong_elsewhere = make_job(
        location="San Francisco, CA",
        title="AI/ML Engineer",
        description="RAG, LangChain, Python, Java, Kafka, AWS, Kubernetes, Docker, Terraform.",
    )
    # ...vs a weak-fit job in Buffalo, NY.
    weak_in_buffalo = make_job(
        location="Buffalo, NY",
        title="Software Engineer",
        description="General role, no strong keyword overlap.",
    )

    ranked = rank_jobs([strong_elsewhere, weak_in_buffalo], weights=weights)

    # Confirm the fit scores really would have ranked the other way without
    # location prioritization, so this test is actually checking something.
    assert strong_elsewhere.fit_score > weak_in_buffalo.fit_score
    assert ranked[0] is weak_in_buffalo
    assert ranked[1] is strong_elsewhere


def test_rank_jobs_orders_multiple_preferred_location_jobs_by_fit_score(make_job):
    profile = CandidateProfile(
        years_of_experience=4.0,
        skills={"java": 2.0, "kafka": 2.0},
        target_roles={},
        domain_experience=[],
        projects=[],
        preferred_locations=["buffalo"],
    )
    weights = RankingWeights(profile=profile)

    strong_buffalo = make_job(location="Buffalo, NY", description="Java, Kafka role.")
    weak_buffalo = make_job(location="Buffalo, NY", description="General role.")

    ranked = rank_jobs([weak_buffalo, strong_buffalo], weights=weights)

    assert ranked[0] is strong_buffalo
    assert ranked[1] is weak_buffalo


def test_default_profile_prioritizes_buffalo():
    profile = default_profile()
    assert any("buffalo" in loc.lower() for loc in profile.preferred_locations)
