"""Environment-driven configuration.

Board/company lists are the one exception: those come from a plain
editable file (config/boards.json, see jobsearch.boards_config) rather
than an environment variable, so they can be changed without touching any
CI workflow YAML. GREENHOUSE_BOARDS/LEVER_COMPANIES env vars still work
and take precedence when set — handy for a quick local override — but the
boards file is what a scheduled run actually reads by default.

Everything else here is read from environment variables, never
hard-coded. Copy .env.example to .env locally and export those variables
(or load them with a tool like python-dotenv/direnv) before running the
CLI.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

from jobsearch.boards_config import DEFAULT_BOARDS_CONFIG_PATH, BoardsConfig


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
    # Where JsonFileSeenJobStore persists stable job ids between runs.
    seen_store_path: str = "data/seen_jobs.json"

    @classmethod
    def from_env(cls) -> "Config":
        env_greenhouse = _split_csv(os.environ.get("GREENHOUSE_BOARDS"))
        env_lever = _split_csv(os.environ.get("LEVER_COMPANIES"))

        if env_greenhouse or env_lever:
            # Explicit env vars set (e.g. for a quick local override) win
            # outright, even if the boards file also has entries.
            greenhouse_boards, lever_companies = env_greenhouse, env_lever
        else:
            boards_config_path = os.environ.get("BOARDS_CONFIG_PATH", DEFAULT_BOARDS_CONFIG_PATH)
            boards = BoardsConfig.from_file(boards_config_path)
            greenhouse_boards, lever_companies = boards.greenhouse_boards, boards.lever_companies

        return cls(
            greenhouse_boards=greenhouse_boards,
            lever_companies=lever_companies,
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

