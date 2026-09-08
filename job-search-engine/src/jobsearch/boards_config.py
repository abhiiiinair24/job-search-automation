"""Board/company configuration for job sources.

Kept in a plain, editable config file (config/boards.json by default)
rather than hard-coded in the CLI, environment variables, or any CI
workflow YAML - so adding/removing a Greenhouse board or Lever company
never requires touching code or the GitHub Actions workflow.

Config.from_env() (see jobsearch.config) uses this as a fallback: if
GREENHOUSE_BOARDS/LEVER_COMPANIES environment variables are set, those
take precedence (handy for quick local overrides); otherwise the boards
file is read.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Union

logger = logging.getLogger(__name__)

DEFAULT_BOARDS_CONFIG_PATH = "config/boards.json"


@dataclass
class BoardsConfig:
    greenhouse_boards: List[str] = field(default_factory=list)
    lever_companies: List[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Union[str, Path] = DEFAULT_BOARDS_CONFIG_PATH) -> "BoardsConfig":
        """Load board/company lists from a JSON file.

        A missing, empty, or malformed file is treated as "no boards
        configured" (logged, not raised) - the search engine already
        handles zero-sources gracefully, and a config problem here
        shouldn't be a hard crash.
        """
        file_path = Path(path)
        if not file_path.exists():
            logger.warning(
                "Boards config file not found at %s; no job sources configured.", file_path
            )
            return cls()

        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Could not read boards config at %s: %s", file_path, exc)
            return cls()

        if not isinstance(data, dict):
            logger.error("Boards config at %s must be a JSON object; ignoring.", file_path)
            return cls()

        greenhouse = data.get("greenhouse_boards", [])
        lever = data.get("lever_companies", [])
        if not isinstance(greenhouse, list) or not isinstance(lever, list):
            logger.error(
                "Boards config at %s: 'greenhouse_boards'/'lever_companies' must be lists; ignoring.",
                file_path,
            )
            return cls()

        return cls(
            greenhouse_boards=[str(b).strip() for b in greenhouse if str(b).strip()],
            lever_companies=[str(c).strip() for c in lever if str(c).strip()],
        )
