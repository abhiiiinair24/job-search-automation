"""HTML email formatting for job-search results.

Pure functions only - no Gmail API, no network, no credentials anywhere in
this module. Given a SearchResult (from jobsearch.engine), it renders
values already computed by the engine/ranking step (fit_explanation,
matched_keywords, sponsorship_status, experience fields, etc.) — it never
invents or re-derives job data, and it never marks anything as seen.

This module can be fully unit-tested with plain Job/SearchResult objects
and zero mocking.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Optional

from jobsearch.engine import SearchResult
from jobsearch.models import Job, SponsorshipStatus

# "10-15 strongest new matches" per spec: show at most this many jobs
# total in the email (top-highlighted + "other matches" combined).
MAX_JOBS_IN_EMAIL = 15
TOP_N_HIGHLIGHT = 4

_SPONSORSHIP_LABELS = {
    SponsorshipStatus.AVAILABLE: "Available",
    SponsorshipStatus.NOT_AVAILABLE: "Not available",
    SponsorshipStatus.UNKNOWN: "Unknown / not mentioned",
}


def _escape(value: Optional[str]) -> str:
    """HTML-escape a value, tolerating None/empty input."""
    return html.escape(value or "", quote=True)


def _format_date(job: Job) -> str:
    date = job.most_recent_date
    return date.strftime("%Y-%m-%d") if date else "unknown"


def _format_experience(job: Job) -> str:
    return job.raw_experience_text or "not specified in posting"


def _format_sponsorship(job: Job) -> str:
    label = _SPONSORSHIP_LABELS[job.sponsorship_status]
    if job.sponsorship_evidence:
        return f'{label} ("{job.sponsorship_evidence}")'
    return label


def _experience_concern(job: Job, candidate_years: Optional[float]) -> Optional[str]:
    """A short note on anything uncertain/risky about the stated requirement."""
    if job.min_experience_years is None:
        return "No experience requirement was stated in the posting - verify fit before applying."
    if job.experience_basis == "tech_specific":
        tech = job.experience_matched_tech or "a specific technology"
        return (
            f"The {job.min_experience_years}+ year figure was only tied to {tech} experience, "
            "not a stated overall requirement - the actual bar may differ."
        )
    if candidate_years is not None and job.min_experience_years > candidate_years:
        return (
            f"Posting asks for {job.min_experience_years}+ years overall, above your "
            f"~{candidate_years:g} years - may be worth addressing directly in your application."
        )
    return None


def _sponsorship_concern(job: Job) -> Optional[str]:
    if job.sponsorship_status == SponsorshipStatus.NOT_AVAILABLE:
        return "This posting explicitly states visa sponsorship is not available."
    if job.sponsorship_status == SponsorshipStatus.UNKNOWN:
        return "Sponsorship isn't mentioned in the posting - confirm directly before investing time."
    return None


def _emphasize_text(job: Job) -> str:
    """What part of the candidate's background to lead with for this job.

    Derived only from job.matched_keywords, which the ranking step already
    computed - this never invents skills the candidate doesn't have.
    """
    if job.matched_keywords:
        return "Emphasize: " + ", ".join(job.matched_keywords[:6])
    return "No specific keyword overlap detected - lead with your closest transferable experience."


def _job_row_html(job: Job) -> str:
    """A compact row for a job in the "other matches" section."""
    return f"""
    <tr>
      <td style="padding:10px 8px;border-bottom:1px solid #e0e0e0;">
        <strong>{_escape(job.title)}</strong> &mdash; {_escape(job.company)}<br/>
        <span style="color:#555;">{_escape(job.location)}</span><br/>
        Posted/updated: {_escape(_format_date(job))}<br/>
        Experience: {_escape(_format_experience(job))}<br/>
        Sponsorship: {_escape(_format_sponsorship(job))}<br/>
        Fit score: {job.fit_score:g}<br/>
        Why it matches: {_escape(job.fit_explanation)}<br/>
        <a href="{_escape(job.url)}">Apply</a>
      </td>
    </tr>"""


def _top_job_html(job: Job, candidate_years: Optional[float], rank: int) -> str:
    """A highlighted card for one of the top-N jobs, with concerns called out."""
    exp_concern = _experience_concern(job, candidate_years)
    sponsor_concern = _sponsorship_concern(job)

    exp_concern_html = (
        f'<br/><span style="color:#b45309;">Concern: {_escape(exp_concern)}</span>'
        if exp_concern
        else ""
    )
    sponsor_concern_html = (
        f'<br/><span style="color:#b45309;">Concern: {_escape(sponsor_concern)}</span>'
        if sponsor_concern
        else ""
    )

    return f"""
    <div style="border:2px solid #2a6df4;border-radius:8px;padding:14px;margin-bottom:14px;">
      <h3 style="margin:0 0 4px 0;">#{rank}: {_escape(job.title)} &mdash; {_escape(job.company)}</h3>
      <p style="margin:2px 0;color:#555;">
        {_escape(job.location)} &middot; Posted/updated {_escape(_format_date(job))}
      </p>
      <p style="margin:8px 0;"><strong>Why it's a strong match:</strong> {_escape(job.fit_explanation)}</p>
      <p style="margin:8px 0;">
        <strong>Experience:</strong> {_escape(_format_experience(job))}{exp_concern_html}
      </p>
      <p style="margin:8px 0;">
        <strong>Sponsorship:</strong> {_escape(_format_sponsorship(job))}{sponsor_concern_html}
      </p>
      <p style="margin:8px 0;"><strong>{_escape(_emphasize_text(job))}</strong></p>
      <p style="margin:8px 0;">Fit score: {job.fit_score:g}</p>
      <p style="margin:8px 0;">
        <a href="{_escape(job.url)}" style="font-weight:bold;">Apply here</a>
      </p>
    </div>"""


def format_email_subject(result: SearchResult) -> str:
    """Subject line reflecting the actual number of new matches (never fabricated)."""
    count = len(result.new_jobs)
    if count == 0:
        return "Job Search Update — no new matches"
    return f"Job Search Update — {count} new match{'es' if count != 1 else ''}"


def format_search_result_email(
    result: SearchResult,
    generated_at: Optional[datetime] = None,
    candidate_years: Optional[float] = None,
    max_jobs: int = MAX_JOBS_IN_EMAIL,
    top_n: int = TOP_N_HIGHLIGHT,
) -> str:
    """Render a SearchResult into a full HTML email body.

    Uses result.new_jobs (this is what "new matching jobs" means per the
    engine's seen/new split; if no seen_store was used, new_jobs equals
    the full ranked list — see jobsearch.engine.run_search). If there are
    zero new jobs, a short "nothing new" email is rendered instead of a
    jobs table — no jobs are ever fabricated to fill space.
    """
    generated_at = generated_at or datetime.now(timezone.utc)
    timestamp_str = generated_at.strftime("%Y-%m-%d %H:%M UTC")

    jobs = result.new_jobs
    count = len(jobs)

    if count == 0:
        return f"""<html><body style="font-family:Arial,Helvetica,sans-serif;">
<h2>Job Search Update &mdash; {timestamp_str}</h2>
<p>No new matching jobs were found in this run.</p>
</body></html>"""

    capped_jobs = jobs[:max_jobs]
    top_jobs = capped_jobs[:top_n]
    remaining_jobs = capped_jobs[top_n:]

    top_html = "".join(
        _top_job_html(job, candidate_years, rank=i) for i, job in enumerate(top_jobs, start=1)
    )

    remaining_section = ""
    if remaining_jobs:
        rows = "".join(_job_row_html(job) for job in remaining_jobs)
        remaining_section = f"""
<h3>Other strong matches</h3>
<table style="width:100%;border-collapse:collapse;">{rows}</table>"""

    shown_note = ""
    if count > max_jobs:
        shown_note = f" (showing the top {max_jobs})"

    plural = "s" if count != 1 else ""
    return f"""<html><body style="font-family:Arial,Helvetica,sans-serif;">
<h2>Job Search Update &mdash; {timestamp_str}</h2>
<p><strong>{count}</strong> new matching job{plural} found{shown_note}.</p>
<h3>Top {len(top_jobs)} matches</h3>
{top_html}
{remaining_section}
</body></html>"""
