"""Fit scoring / ranking of jobs against a candidate profile.

All person-specific data (skills, target roles, years of experience,
preferred locations) lives in `jobsearch.profile.CandidateProfile`, not
here — this module only holds the scoring *mechanism*. See profile.py to
update or swap the profile being ranked against.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from jobsearch.filters.experience import extract_experience_requirement
from jobsearch.keyword_match import contains_keyword
from jobsearch.models import Job, SponsorshipStatus
from jobsearch.profile import CandidateProfile, default_profile


@dataclass
class RankingWeights:
    profile: CandidateProfile = field(default_factory=default_profile)
    new_grad_penalty: float = 4.0
    sponsorship_not_available_penalty: float = 3.0
    sponsorship_available_bonus: float = 1.5
    experience_mismatch_penalty: float = 2.0
    remote_bonus: float = 0.5
    # Added to a job's fit score when its location matches one of the
    # profile's preferred_locations. rank_jobs() additionally guarantees
    # preferred-location jobs sort ahead of all others regardless of fit
    # score - this bonus mainly affects ordering *within* that group.
    preferred_location_bonus: float = 6.0

    @property
    def candidate_years(self) -> float:
        return self.profile.years_of_experience


def _matched_preferred_location(job: Job, preferred_locations: List[str]) -> Optional[str]:
    """The first preferred-location keyword found in job.location, if any."""
    for location_keyword in preferred_locations:
        if contains_keyword(job.location, location_keyword):
            return location_keyword
    return None


def score_job(job: Job, weights: Optional[RankingWeights] = None) -> Job:
    """Compute and attach a fit score + short explanation to a job, in place."""
    weights = weights or RankingWeights()
    profile = weights.profile
    haystack = f"{job.title} {job.description}".lower()

    matched: List[str] = []
    score = 0.0

    for keyword, weight in profile.skills.items():
        if contains_keyword(haystack, keyword):
            score += weight
            matched.append(keyword)

    title_lower = job.title.lower()
    best_title_match: Optional[str] = None
    for keyword, weight in profile.target_roles.items():
        if contains_keyword(title_lower, keyword):
            score += weight
            if best_title_match is None:
                best_title_match = keyword

    for domain in profile.domain_experience:
        if contains_keyword(haystack, domain):
            score += 1.0
            matched.append(domain.lower())

    # Experience alignment: reward requirements centered near the
    # candidate's actual years; penalize once a min requirement is known
    # and exceeds what the candidate has.
    if job.min_experience_years is not None:
        gap = abs(job.min_experience_years - weights.candidate_years)
        score -= gap * weights.experience_mismatch_penalty * 0.25
        if job.min_experience_years > weights.candidate_years:
            score -= weights.experience_mismatch_penalty

    # De-prioritize (not exclude) new-grad postings.
    if extract_experience_requirement(job.description).is_new_grad_signal:
        score -= weights.new_grad_penalty

    # Sponsorship signal.
    if job.sponsorship_status == SponsorshipStatus.NOT_AVAILABLE:
        score -= weights.sponsorship_not_available_penalty
    elif job.sponsorship_status == SponsorshipStatus.AVAILABLE:
        score += weights.sponsorship_available_bonus

    if job.is_remote:
        score += weights.remote_bonus

    matched_location = _matched_preferred_location(job, profile.preferred_locations)
    if matched_location:
        score += weights.preferred_location_bonus

    job.fit_score = round(score, 2)
    job.matched_keywords = sorted(set(matched))

    explanation_parts = []
    if best_title_match:
        explanation_parts.append(f"title matches target role '{best_title_match}'")
    if matched_location:
        explanation_parts.append(f"preferred location match ({job.location})")
    if matched:
        weight_lookup = {**profile.skills, **{d.lower(): 1.0 for d in profile.domain_experience}}
        top_matches = sorted(matched, key=lambda k: weight_lookup.get(k, 0.0), reverse=True)[:5]
        explanation_parts.append("matches on: " + ", ".join(top_matches))
    if job.sponsorship_status != SponsorshipStatus.UNKNOWN:
        explanation_parts.append(f"sponsorship: {job.sponsorship_status.value}")
    job.fit_explanation = (
        "; ".join(explanation_parts) if explanation_parts else "limited keyword overlap detected"
    )

    return job


def rank_jobs(jobs: Iterable[Job], weights: Optional[RankingWeights] = None) -> List[Job]:
    """Score every job and return them sorted best-first.

    Jobs matching one of the profile's preferred_locations are always
    sorted ahead of jobs that don't, regardless of fit score - this is a
    hard priority tier (e.g. "show me everything in Buffalo, NY first"),
    not just a scoring nudge. Within each tier, jobs are sorted by
    descending fit score.
    """
    weights = weights or RankingWeights()
    preferred_locations = weights.profile.preferred_locations
    scored = [score_job(job, weights) for job in jobs]

    def sort_key(job: Job):
        is_preferred = _matched_preferred_location(job, preferred_locations) is not None
        return (0 if is_preferred else 1, -job.fit_score)

    return sorted(scored, key=sort_key)
