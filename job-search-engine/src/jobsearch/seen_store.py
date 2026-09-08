"""Abstraction for tracking which jobs have already been seen.

This does NOT wire into any scheduler yet (no GitHub Actions) — it only
makes the engine ready for that: given a store, the engine can ask "which
of these jobs are new?" and a caller can later mark jobs as seen once
they've been acted on (e.g. emailed). Two implementations are provided:

- InMemorySeenJobStore: process-local, resets every run. Useful for tests
  and one-off CLI runs where persistence isn't needed.
- JsonFileSeenJobStore: persists stable job ids to a JSON file on disk, so
  "seen" status survives across separate runs (e.g. a future scheduled
  job). The file path is configurable (see Config.seen_store_path).
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, List, Set, Union

logger = logging.getLogger(__name__)


class SeenJobStoreWriteError(Exception):
    """Raised when persisting seen-job state to disk fails.

    Unlike read failures (treated leniently as "nothing seen yet" so a
    damaged/missing file never blocks a run), a WRITE failure is not safe
    to swallow: silently failing to persist "seen" state would cause the
    same jobs to be re-emailed on every subsequent run. Callers (e.g. the
    orchestrator) should let this propagate and fail the run clearly.
    """


class SeenJobStore(ABC):
    """Common interface for tracking which job stable_ids have been seen before."""

    @abstractmethod
    def get_seen_ids(self) -> Set[str]:
        """Return the full set of stable ids already marked as seen."""
        raise NotImplementedError

    @abstractmethod
    def mark_seen(self, job_ids: Iterable[str]) -> None:
        """Persist the given stable ids as seen, in addition to any already stored."""
        raise NotImplementedError

    def filter_new(self, job_ids: Iterable[str]) -> List[str]:
        """Return only the ids from job_ids that have NOT been seen before."""
        seen = self.get_seen_ids()
        return [job_id for job_id in job_ids if job_id not in seen]


class InMemorySeenJobStore(SeenJobStore):
    """Process-local seen-id tracking; does not persist across runs."""

    def __init__(self, initial_seen: Iterable[str] = ()) -> None:
        self._seen: Set[str] = set(initial_seen)

    def get_seen_ids(self) -> Set[str]:
        return set(self._seen)

    def mark_seen(self, job_ids: Iterable[str]) -> None:
        self._seen.update(job_ids)


class JsonFileSeenJobStore(SeenJobStore):
    """Persists seen stable-ids as a JSON array of strings on disk.

    A missing, empty, or corrupt/unreadable file is treated as "nothing
    seen yet" rather than raising, so a fresh or damaged store never blocks
    a run — the read error is logged instead.
    """

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path)

    def get_seen_ids(self) -> Set[str]:
        if not self.path.exists():
            return set()
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read seen-job store at %s: %s", self.path, exc)
            return set()

        if not isinstance(data, list):
            logger.warning("Seen-job store at %s did not contain a JSON list; ignoring.", self.path)
            return set()
        return {str(item) for item in data}

    def mark_seen(self, job_ids: Iterable[str]) -> None:
        current = self.get_seen_ids()
        current.update(job_ids)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(sorted(current), f, indent=2)
        except OSError as exc:
            raise SeenJobStoreWriteError(
                f"Could not write seen-job store at {self.path}: {exc}"
            ) from exc
