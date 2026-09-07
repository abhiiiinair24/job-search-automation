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
