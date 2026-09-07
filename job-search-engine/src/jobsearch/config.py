"""Environment-driven configuration.

No secrets are needed by the current (core-engine-only) scope, but this
module is where any future API keys/tokens would be read from — always via
environment variables, never hard-coded or committed. Copy .env.example to
.env locally and export those variables (or load them with a tool like
python-dotenv/direnv) before running the CLI.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional


def _split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Config:
    greenhouse_boards: List[str] = field(default_factory=list)
    lever_companies: List[str] = field(default_factory=list)
    recency_days: int = 4
    hard_exclude_experience_years: int = 6
    candidate_experience_years: float = 4.0
    log_level: str = "INFO"
    results_limit: int = 15
    # Where JsonFileSeenJobStore persists stable job ids between runs. Not
    # wired into the CLI yet (no scheduler exists), but configurable now so
    # a future scheduled run can point it somewhere durable.
    seen_store_path: str = "data/seen_jobs.json"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            greenhouse_boards=_split_csv(os.environ.get("GREENHOUSE_BOARDS")),
            lever_companies=_split_csv(os.environ.get("LEVER_COMPANIES")),
            recency_days=int(os.environ.get("RECENCY_DAYS", "4")),
            hard_exclude_experience_years=int(
                os.environ.get("HARD_EXCLUDE_EXPERIENCE_YEARS", "6")
            ),
            candidate_experience_years=float(
                os.environ.get("CANDIDATE_EXPERIENCE_YEARS", "4")
            ),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            results_limit=int(os.environ.get("RESULTS_LIMIT", "15")),
            seen_store_path=os.environ.get("SEEN_STORE_PATH", "data/seen_jobs.json"),
        )


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
