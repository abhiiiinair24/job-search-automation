"""End-to-end scheduled run: fetch -> filter -> rank -> email -> mark seen.

This is what ties the core engine, the candidate profile, the Gmail email
layer, and persistent seen-job tracking into the single script a scheduler
(GitHub Actions) or a person runs. None of the underlying pieces know
about each other directly - this module is where the orchestration
decision actually lives:

    run_search() -> send email -> CONFIRM success -> THEN mark_seen()

A failed send must never mark jobs as seen (they'd be silently dropped
from the next run's results, having never actually reached anyone). A
failed state write must not be swallowed either - it would cause the same
jobs to be re-emailed on every subsequent run - so it's left to propagate
and fail the run clearly, same as an email failure.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import List, Optional

from jobsearch.config import Config, configure_logging
from jobsearch.email.config import EmailConfig, EmailConfigError
from jobsearch.email.gmail_auth import GmailAuthConfigError
from jobsearch.email.gmail_sender import GmailSendError, send_search_result_email
from jobsearch.engine import SearchResult, run_search
from jobsearch.profile import default_profile
from jobsearch.seen_store import JsonFileSeenJobStore, SeenJobStore, SeenJobStoreWriteError
from jobsearch.sources.base import JobSource

logger = logging.getLogger(__name__)


class OrchestrationError(Exception):
    """Raised when the scheduled run cannot complete successfully.

    Anything that reaches main() as this exception exits with a non-zero
    status, which fails the GitHub Actions step clearly rather than
    silently continuing.
    """


@dataclass
class OrchestrationResult:
    result: SearchResult
    email_sent: bool
    marked_seen_count: int
    gmail_message_id: Optional[str] = None


def run_scheduled_search(
    config: Optional[Config] = None,
    seen_store: Optional[SeenJobStore] = None,
    email_config: Optional[EmailConfig] = None,
    sources: Optional[List[JobSource]] = None,
) -> OrchestrationResult:
    """Run one full scheduled cycle.

    Raises OrchestrationError for anything that should fail the run:
    missing/invalid email configuration, a Gmail send failure, or a
    seen-state write failure. In every one of those cases, no jobs are
    marked as seen - only a *confirmed successful* send does that.

    `sources` can be injected directly (used in tests, and useful for
    wiring in a source that isn't Greenhouse/Lever); otherwise sources are
    built from `config.greenhouse_boards` / `config.lever_companies`
    (which in turn default to config/boards.json - see jobsearch.config).
    """
    config = config or Config.from_env()
    seen_store = seen_store or JsonFileSeenJobStore(path=config.seen_store_path)
    profile = default_profile(years_of_experience=config.candidate_experience_years)

    logger.info("Starting scheduled job search run.")
    result = run_search(config, sources=sources, profile=profile, seen_store=seen_store)

    logger.info(
        "Fetched %d posting(s); %d passed filters; %d new, %d already seen.",
        result.total_fetched,
        result.total_after_filters,
        len(result.new_jobs),
        len(result.already_seen_jobs),
    )
    for source_name in result.failed_sources:
        logger.warning("Source failed or returned no postings: %s", source_name)

    try:
        response = send_search_result_email(
            result,
            email_config=email_config,
            candidate_years=config.candidate_experience_years,
        )
    except (EmailConfigError, GmailAuthConfigError) as exc:
        raise OrchestrationError(f"Email/Gmail configuration is invalid: {exc}") from exc
    except GmailSendError as exc:
        # Per spec: a failed send must NOT mark anything as seen, so the
        # same jobs are correctly retried as "new" on the next run.
        raise OrchestrationError(f"Gmail send failed - no jobs marked as seen: {exc}") from exc

    logger.info("Email sent successfully (Gmail message id=%s).", response.get("id"))

    new_ids = [job.stable_id for job in result.new_jobs]
    if new_ids:
        try:
            seen_store.mark_seen(new_ids)
        except SeenJobStoreWriteError as exc:
            # The email already went out - but if we can't record that,
            # the same jobs will be re-emailed next run. Fail loudly
            # rather than silently losing that guarantee.
            raise OrchestrationError(
                f"Email sent successfully, but failed to persist seen-job state "
                f"(next run may re-send these {len(new_ids)} job(s)): {exc}"
            ) from exc
        logger.info("Marked %d job(s) as seen.", len(new_ids))
    else:
        logger.info("No new jobs to mark as seen.")

    return OrchestrationResult(
        result=result,
        email_sent=True,
        marked_seen_count=len(new_ids),
        gmail_message_id=response.get("id"),
    )


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point for `python -m jobsearch.orchestrator` / the `jobsearch-send` script."""
    config = Config.from_env()
    configure_logging(config.log_level)

    try:
        outcome = run_scheduled_search(config=config)
    except OrchestrationError as exc:
        logger.error(str(exc))
        return 1

    print(
        f"Done. {len(outcome.result.new_jobs)} new job(s) found; "
        f"email sent (id={outcome.gmail_message_id}); "
        f"{outcome.marked_seen_count} job(s) marked as seen."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
