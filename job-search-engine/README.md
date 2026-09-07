# jobsearch — automated job-search engine (core)

This is the **core engine only** — fetch, filter, dedupe, rank, and print
job postings from Greenhouse and Lever boards. It does **not** yet include
GitHub Actions scheduling or Gmail delivery; those are explicitly out of
scope for this pass.

## Architecture

```
src/jobsearch/
  models.py            Job dataclass, SponsorshipStatus/SourceType enums,
                        stable_id (dedup key) and most_recent_date helpers
  config.py             Config dataclass, loaded entirely from env vars
  keyword_match.py        Word-boundary-safe keyword matching, shared by
                          ranking.py and filters/experience.py
  profile.py             CandidateProfile dataclass + default_profile() —
                          your skills/roles/experience/preferred locations,
                          kept out of ranking.py
  seen_store.py           SeenJobStore abstraction (in-memory + JSON-backed)
                          for tracking which jobs have already been surfaced
  sources/
    base.py             JobSource ABC + safe_fetch_jobs() error boundary
    greenhouse.py        Greenhouse public job-board API integration
    lever.py             Lever public postings API integration
  filters/
    experience.py         Years-of-experience extraction (overall vs.
                          tech-specific) + hard filter
    recency.py             "posted/updated in the last N days" filter
    sponsorship.py         Heuristic visa-sponsorship detection
    location.py            US-only (incl. remote) location filter
  dedup.py               Stable-id-based deduplication
  ranking.py              Keyword-weighted fit scoring; consumes a
                          CandidateProfile rather than embedding one
  engine.py               Orchestrates: fetch -> dedup -> annotate -> filter
                          -> rank, with optional profile/seen_store injection
  cli.py                  argparse CLI, prints a formatted report

tests/                   161 unit/integration tests, no real network calls
```

### Design decisions worth knowing about

- **Sources are public, read-only APIs, no auth required.** Greenhouse
  (`boards-api.greenhouse.io`) and Lever (`api.lever.co`) both expose public
  JSON endpoints keyed by a company's board token/slug — no API key needed,
  hence no secrets to manage yet.
- **Stable IDs for dedup:** `f"{source}:{native_job_id}"` (e.g.
  `greenhouse:4821093`). This is what you'd persist between runs to know
  whether a posting is new or already seen. A hash-based fallback exists
  for the (rare) case a source doesn't expose a native id.
- **Experience filtering is a soft-first, hard-second design:** only jobs
  that explicitly state a minimum of 6+ years are hard-excluded. Everything
  else (unstated requirements, 0-5 year ranges, new-grad postings) passes
  the filter — new-grad postings are instead penalized in the *ranking*
  step, per "do not prioritize new-grad roles" rather than "exclude them."
- **Experience extraction distinguishes overall vs. tech-specific
  mentions.** "3+ years of Python experience and 7+ years of engineering
  experience" correctly resolves to an overall requirement of 7, not 3 —
  the parser scopes each years-mention to its own clause (split on
  punctuation/"and") and classifies it as general ("software engineering",
  "professional experience", or no qualifier at all) vs. tied to a named
  technology. A general mention always wins; a tech-specific mention is
  only used as a fallback when no general requirement is stated anywhere
  in the posting. This is regex/heuristic, not ML — see
  `filters/experience.py` for the exact keyword lists.
- **Skill/title/domain matching is word-boundary aware, not plain
  substring search.** `jobsearch/keyword_match.py` fixes a real bug where
  short keywords like "rag" matched inside unrelated words — "storage"
  and "leverage" both contain the substring "rag" — or "sql" matched
  inside "mysql". Matching now requires the keyword not be immediately
  preceded/followed by a letter or digit, so "rag" only matches as the
  whole word "RAG", not as a substring of "average", "storage",
  "leverage", or "paragraph". This is used everywhere keywords are
  matched against job text: `ranking.py` (skills, target roles, domain
  experience) and `filters/experience.py` (overall-vs-tech-specific
  classification).
- **Preferred-location prioritization (e.g. Buffalo, NY).**
  `CandidateProfile.preferred_locations` (set to `["buffalo"]` in the
  default profile, since Abhishek studies and resides there) is a hard
  priority tier in `rank_jobs()`: every job matching a preferred location
  is sorted ahead of every job that doesn't, regardless of fit score — not
  just a scoring nudge. Within each tier, jobs are still sorted by
  descending fit score. A fit-score bonus (`preferred_location_bonus`) is
  also applied so the "why it matches" explanation and ordering *within*
  the preferred-location group make sense on their own.
  `CandidateProfile` is a plain dataclass (skills, target roles, years of
  experience, domain experience, projects); `default_profile()` builds the
  one used for Abhishek from what he's actually provided — nothing
  invented, and `projects` is intentionally empty since none were named
  yet. `ranking.py` only holds the scoring mechanism and takes a
  `CandidateProfile` as input, so ranking against an updated or different
  profile is a matter of constructing a new one, not editing scoring code.
- **Seen-job tracking is ready but not wired into a scheduler.**
  `SeenJobStore` (in `seen_store.py`) is an abstract interface with two
  implementations: `InMemorySeenJobStore` (process-local, for tests/one-off
  runs) and `JsonFileSeenJobStore` (persists stable ids to a JSON file at a
  configurable path — see `SEEN_STORE_PATH` in `.env.example`).
  `engine.run_search(..., seen_store=...)` splits results into
  `new_jobs` / `already_seen_jobs`, but never marks anything as seen on its
  own — a caller (eventually, the GitHub Actions job) decides when to call
  `store.mark_seen(...)`, presumably after successfully notifying about
  the new ones.
- **Sponsorship detection is heuristic and text-only.** It only classifies
  a posting as available/not-available when the text explicitly says so;
  most postings say nothing, and those are `unknown` rather than assumed
  either way. Treat this as a first-pass signal, not a guarantee — always
  verify sponsorship on the actual application page for jobs you care about.
- **Location filtering is heuristic**, based on US state abbreviations,
  "United States"/"USA" strings, and a "Remote" allowance per your
  requirement that Remote-US is acceptable. It excludes locations that
  clearly name a non-US country/region.
- **Ranking is a transparent, tunable keyword-weighted score** (see
  `ranking.py::DEFAULT_SKILL_WEIGHTS` and `TARGET_TITLE_KEYWORDS`), not a
  black box — the weights reflect your actual background (Java/Spring
  Boot/Kafka/distributed systems/payments from HSBC, plus PyTorch/LangChain/
  RAG/MCP from your Master's and recent projects). Each job also gets a
  short human-readable `fit_explanation`.
- **Every fetch is wrapped in a try/except boundary** (`safe_fetch_jobs`)
  so one broken/unreachable source never crashes the whole run — it's
  logged and reported in the run summary instead.

## Running locally

```bash
cd job-search-engine
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# edit .env: set GREENHOUSE_BOARDS and/or LEVER_COMPANIES to real
# company board tokens/slugs, e.g.:
#   GREENHOUSE_BOARDS=stripe,airbnb
#   LEVER_COMPANIES=netflix

export $(grep -v '^#' .env | xargs)   # or use direnv/python-dotenv
python3 -m jobsearch.cli --limit 15 --top 4
```

Finding board tokens: a company's Greenhouse board token is the slug in
`https://boards.greenhouse.io/<token>`; a Lever slug is the one in
`https://jobs.lever.co/<slug>`. Not every company uses Greenhouse or Lever
— this integration only covers those two ATS platforms for now, per the
current scope.

## Running the tests

```bash
python3 -m pytest -v          # verbose
python3 -m pytest --cov=jobsearch --cov-report=term-missing   # with coverage
```

All source-fetching tests mock `requests.get` — no real network calls are
made during the test suite, so it's fully offline and deterministic.

## Known limitations (current scope)

- Only Greenhouse and Lever are implemented. Companies using Workday,
  iCIMS, Ashby, LinkedIn, etc. aren't covered yet.
- Experience-requirement and sponsorship detection are regex/heuristic —
  they won't catch every phrasing a job posting might use, and should be
  treated as a first pass, not ground truth.
- The "seen before" dedup mechanism computes stable IDs but doesn't yet
  persist them anywhere (e.g. to a file or database) between CLI runs —
  each run currently only dedupes within that run's own fetch. Persisting
  a "seen" set is a natural next step once GitHub Actions scheduling is
  added.
- No GitHub Actions workflow and no Gmail delivery yet — by design, per
  this task's scope.
- This sandbox's outbound network is restricted to a small domain
  allowlist that doesn't include `boards-api.greenhouse.io` or
  `api.lever.co`, so live fetching couldn't be verified end-to-end here.
  It will work from a normal machine/CI runner with standard internet
  access — the graceful-failure path (a 403 in this sandbox) was
  confirmed to log the error and continue rather than crash.
