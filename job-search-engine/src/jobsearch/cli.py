"""Command-line entry point for the job-search engine.

Usage:
    python -m jobsearch.cli
    jobsearch --limit 15 --top 4    (after `pip install -e .`)
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from jobsearch.config import Config, configure_logging
from jobsearch.engine import run_search
from jobsearch.models import Job

logger = logging.getLogger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobsearch",
        description="Fetch, filter, and rank job postings from Greenhouse/Lever boards.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of jobs to print overall (default: RESULTS_LIMIT env var, or 15).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=4,
        help="How many of the top-ranked jobs to highlight up front (default: 4).",
    )
    return parser


def format_job(job: Job, rank: int) -> str:
    posted = job.most_recent_date.strftime("%Y-%m-%d") if job.most_recent_date else "unknown"
    sponsorship = job.sponsorship_status.value
    if job.sponsorship_evidence:
        sponsorship += f" (matched: \"{job.sponsorship_evidence}\")"

    lines = [
        f"{rank}. {job.title} — {job.company}",
        f"   Location: {job.location or 'unknown'}",
        f"   Posted/updated: {posted}",
        f"   Experience: {job.raw_experience_text or 'not specified in posting'}",
        f"   Sponsorship: {sponsorship}",
        f"   Apply: {job.url or 'no URL available'}",
        f"   Fit score: {job.fit_score}",
        f"   Why it matches: {job.fit_explanation}",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    config = Config.from_env()
    configure_logging(config.log_level)

    if not config.greenhouse_boards and not config.lever_companies:
        logger.warning(
            "No GREENHOUSE_BOARDS or LEVER_COMPANIES configured. "
            "Set them as comma-separated board/company slugs (see .env.example)."
        )

    result = run_search(config)
    limit = args.limit if args.limit is not None else config.results_limit
    jobs = result.jobs[:limit]

    print(
        f"Fetched {result.total_fetched} raw postings; "
        f"{result.total_after_filters} passed all filters."
    )
    if result.failed_sources:
        print(f"Sources with no results/errors: {', '.join(result.failed_sources)}")
    print()

    if not jobs:
        print("No matching jobs found for the configured sources and filters.")
        return 0

    top_n = min(args.top, len(jobs))
    print(f"=== Top {top_n} matches ===\n")
    for i, job in enumerate(jobs[:top_n], start=1):
        print(format_job(job, i))
        print()

    if len(jobs) > top_n:
        print(f"=== Remaining matches ({len(jobs) - top_n}) ===\n")
        for i, job in enumerate(jobs[top_n:], start=top_n + 1):
            print(format_job(job, i))
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
