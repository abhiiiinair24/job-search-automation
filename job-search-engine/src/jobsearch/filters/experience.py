"""Experience-requirement extraction and filtering.

Job descriptions phrase years-of-experience requirements in many
inconsistent ways, and often mix a general/overall requirement with one or
more technology-specific mentions in the same posting, e.g.:

    "3+ years of Python experience and 7+ years of engineering experience"

This module tries to distinguish those two cases heuristically:

- OVERALL: phrased as general software/engineering/professional/industry
  experience, or with no technology qualifier at all (a bare "5+ years of
  experience").
- TECH_SPECIFIC: tied to a specific named technology ("Python experience",
  "experience with Kafka").

When both kinds of mention are present in the same posting, the overall
requirement wins, since that's the actual bar a candidate needs to clear.
When only a tech-specific mention exists, it's used as a best-effort
fallback (it's the only signal we have), but is tagged with
`basis="tech_specific"` so callers can treat it with appropriately lower
confidence.

This is a heuristic, deterministic parser — no ML/LLM involved. It is not
guaranteed to catch every phrasing; when nothing matches, the requirement
is treated as unknown rather than excluded, since we shouldn't drop a
posting just because we failed to parse it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from jobsearch.keyword_match import contains_keyword
from jobsearch.models import Job

# Technologies/tools specific enough that a "years of experience" mention
# tied to one of them should NOT be treated as the posting's overall
# requirement, unless no overall requirement is stated anywhere else in
# the posting. Order doesn't matter; matched via substring search.
TECH_KEYWORDS = [
    "python", "java", "kotlin", "javascript", "typescript", "c++", "c#",
    "golang", "ruby", "php", "scala", "swift",
    "spring boot", "spring", "kafka", "react native", "react", "next.js",
    "angular", "vue",
    "aws", "gcp", "azure", "kubernetes", "docker", "terraform",
    "postgresql", "postgres", "mysql", "oracle", "mongodb", "cassandra",
    "pytorch", "tensorflow", "langchain", "langgraph", "pyspark", "spark",
    "hadoop", "bigquery", "sql",
]

# Phrasing that signals a general/overall experience requirement rather
# than one tied to a specific technology.
OVERALL_CONTEXT_KEYWORDS = [
    "software engineering", "software development", "engineering experience",
    "professional experience", "industry experience", "overall experience",
    "total experience", "relevant experience", "work experience",
    "programming experience", "development experience", "coding experience",
    "hands-on experience",
]

_EXPERIENCE_INDICATOR_RE = re.compile(r"experience|exp\.", re.IGNORECASE)

# A clause boundary: sentence/list punctuation or a coordinating "and",
# used to scope how much surrounding text we look at when classifying a
# given years-mention, so a neighboring clause about a different
# technology (or the overall requirement) doesn't bleed into this one.
_CLAUSE_BOUNDARY_RE = re.compile(r"[.;,]|\band\b", re.IGNORECASE)

_YEARS_RE = re.compile(
    r"(?:(?P<atleast>at least|minimum(?:\s+of)?)\s*)?"
    r"(?P<lo>\d{1,2})"
    r"(?P<plus>\+)?"
    r"(?:\s*(?:-|to)\s*(?P<hi>\d{1,2})\+?)?"
    r"\s*years?",
    re.IGNORECASE,
)

_NEW_GRAD_RE = re.compile(
    r"new grad|entry[\s-]level|recent graduate|university grad|"
    r"no prior experience required|early[\s-]career",
    re.IGNORECASE,
)


@dataclass
class ExperienceRequirement:
    min_years: Optional[int]
    max_years: Optional[int]
    is_new_grad_signal: bool
    basis: str = "unspecified"  # "overall" | "tech_specific" | "unspecified"
    matched_tech: Optional[str] = None


@dataclass
class _YearsMention:
    min_years: int
    max_years: Optional[int]
    basis: str
    matched_tech: Optional[str]


def _classify_context(context: str) -> Tuple[str, Optional[str]]:
    """Given a lowercased clause of text around a years-mention, classify it."""
    for keyword in OVERALL_CONTEXT_KEYWORDS:
        if contains_keyword(context, keyword):
            return "overall", None
    for keyword in TECH_KEYWORDS:
        if contains_keyword(context, keyword):
            return "tech_specific", keyword
    return "unspecified", None


def _local_clause(text: str, start: int, end: int) -> str:
    """The clause containing text[start:end], bounded by punctuation/'and'."""
    before_matches = list(_CLAUSE_BOUNDARY_RE.finditer(text, 0, start))
    before_idx = before_matches[-1].end() if before_matches else 0
    after_match = _CLAUSE_BOUNDARY_RE.search(text, end)
    after_idx = after_match.start() if after_match else len(text)
    return text[before_idx:after_idx]


def _find_years_mentions(text: str) -> List[_YearsMention]:
    mentions: List[_YearsMention] = []
    for match in _YEARS_RE.finditer(text):
        start, end = match.span()
        clause = _local_clause(text, start, end).lower()

        if not _EXPERIENCE_INDICATOR_RE.search(clause):
            continue  # not actually an experience-years mention

        lo = int(match.group("lo"))
        hi_group = match.group("hi")
        is_open_ended = bool(match.group("plus")) or bool(match.group("atleast"))

        if hi_group is not None:
            hi = int(hi_group)
            min_years, max_years = min(lo, hi), max(lo, hi)
        elif is_open_ended:
            min_years, max_years = lo, None
        else:
            # A bare "X years [of] experience" with no +/range/at-least
            # qualifier is treated as an exact requirement.
            min_years, max_years = lo, lo

        basis, matched_tech = _classify_context(clause)
        mentions.append(_YearsMention(min_years, max_years, basis, matched_tech))

    return mentions


def extract_experience_requirement(text: str) -> ExperienceRequirement:
    """Best-effort extraction of a numeric years-of-experience range from free text."""
    if not text:
        return ExperienceRequirement(None, None, False)

    is_new_grad = bool(_NEW_GRAD_RE.search(text))
    mentions = _find_years_mentions(text)

    if not mentions:
        return ExperienceRequirement(None, None, is_new_grad)

    # "overall" and "unspecified" mentions both function as general
    # requirements (we just have more confidence in the former); either
    # kind takes priority over a tech-specific mention.
    general_mentions = [m for m in mentions if m.basis in ("overall", "unspecified")]
    tech_mentions = [m for m in mentions if m.basis == "tech_specific"]

    if general_mentions:
        # The most restrictive (highest) general requirement wins - that's
        # the actual bar a candidate needs to clear.
        best = max(general_mentions, key=lambda m: m.min_years)
        return ExperienceRequirement(best.min_years, best.max_years, is_new_grad, best.basis, None)

    # No overall/unspecified mention anywhere: fall back to the strictest
    # tech-specific mention as our best guess, flagged as such so callers
    # can weight it with lower confidence.
    best = max(tech_mentions, key=lambda m: m.min_years)
    return ExperienceRequirement(
        best.min_years, best.max_years, is_new_grad, "tech_specific", best.matched_tech
    )


def annotate_experience(job: Job) -> Job:
    """Fill in job.min/max_experience_years + basis fields from its text, in place."""
    req = extract_experience_requirement(job.description)
    job.min_experience_years = req.min_years
    job.max_experience_years = req.max_years
    job.experience_matched_tech = req.matched_tech

    if req.min_years is not None or req.max_years is not None:
        job.experience_basis = req.basis
        lo = req.min_years if req.min_years is not None else "?"
        hi = req.max_years if req.max_years is not None else "?"
        if req.basis == "tech_specific" and req.matched_tech:
            job.raw_experience_text = (
                f"{lo}-{hi} years, tech-specific ({req.matched_tech}) (parsed from posting)"
            )
        elif req.basis == "overall":
            job.raw_experience_text = f"{lo}-{hi} years, overall requirement (parsed from posting)"
        else:
            job.raw_experience_text = f"{lo}-{hi} years (parsed from posting)"
    elif req.is_new_grad_signal:
        job.experience_basis = None
        job.raw_experience_text = "new grad / entry level (parsed from posting)"
    else:
        job.experience_basis = None

    return job


def passes_experience_filter(job: Job, hard_exclude_years: int = 6) -> bool:
    """Hard filter: exclude only jobs that explicitly require >= hard_exclude_years.

    Everything else (unknown requirement, new-grad postings, 0-5 year
    ranges) passes this filter. New-grad postings are deprioritized in
    ranking rather than dropped here, per the requirement to not prioritize
    (but not necessarily hard-exclude) them.
    """
    min_years = job.min_experience_years
    if min_years is not None and min_years >= hard_exclude_years:
        return False
    return True
