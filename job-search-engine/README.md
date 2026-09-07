# jobsearch — automated job-search engine + Gmail delivery

This covers the **core engine** (fetch, filter, dedupe, rank job postings
from Greenhouse and Lever boards) plus a **Gmail email-delivery layer**
that turns a search result into an HTML report and sends it via the Gmail
API. It does **not** yet include GitHub Actions scheduling — that
orchestration layer (deciding when to run, and marking jobs as seen after
a successful send) is the next piece, not built yet.

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
  email/
    formatter.py           Pure HTML rendering of a SearchResult - no
                            Gmail/network imports, fully unit-testable
    config.py               EmailConfig (recipient etc.) loaded from env vars
    gmail_auth.py            OAuth2 credential loading from env vars/secrets
                             (no credential files read or written)
    gmail_sender.py           Sends via the Gmail API (not SMTP); the only
                             module in the project that makes Gmail network
                             calls

scripts/
  get_gmail_refresh_token.py  One-time LOCAL script (not part of the
                              package) to obtain a Gmail refresh token via
                              browser OAuth consent

tests/                   220 unit/integration tests, no real network calls
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
- **Candidate profile lives in `profile.py`, not `ranking.py`.**
  `CandidateProfile` is a plain dataclass (skills, target roles, years of
  experience, domain experience, projects); `default_profile()` builds the
  one used for Abhishek from what he's actually provided — nothing
  invented, and `projects` is intentionally empty since none were named
  yet. `ranking.py` only holds the scoring mechanism and takes a
  `CandidateProfile` as input, so ranking against an updated or different
  profile is a matter of constructing a new one, not editing scoring code.
- **Seen-job tracking exists, but nothing calls `mark_seen()` yet.**
  `SeenJobStore` (in `seen_store.py`) is an abstract interface with two
  implementations: `InMemorySeenJobStore` (process-local, for tests/one-off
  runs) and `JsonFileSeenJobStore` (persists stable ids to a JSON file at a
  configurable path — see `SEEN_STORE_PATH` in `.env.example`).
  `engine.run_search(..., seen_store=...)` splits results into
  `new_jobs` / `already_seen_jobs`, but never marks anything as seen on its
  own. The email layer (below) doesn't either — that decision belongs to
  the future orchestration/scheduler layer, which should call
  `store.mark_seen(...)` only after confirming the email actually sent.
- **Gmail delivery is three separately-testable modules, by design.**
  `email/formatter.py` is pure functions (SearchResult in, HTML string
  out) — no Gmail imports at all, so it's tested with zero mocking.
  `email/gmail_auth.py` loads OAuth2 credentials from environment
  variables only (never a credentials/token file) and builds a
  `google.oauth2.credentials.Credentials` from a long-lived refresh token;
  access tokens are always fetched fresh via the refresh grant, so nothing
  needs to persist between CI runs. `email/gmail_sender.py` is the only
  module that makes real Gmail API calls, and is fully mocked in tests.
  See "Gmail API setup" below for the one-time setup this requires.
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

All source-fetching and Gmail-sending tests mock their network calls
(`requests.get`, `googleapiclient.discovery.build`) — no real network
calls are made during the test suite, so it's fully offline and
deterministic.

## Gmail API setup (one-time)

The email layer uses the **Gmail API directly (OAuth2), not SMTP** — this
is the approach Google expects for automated/CI sending, and it uses a
narrow `gmail.send`-only scope (this app can never read your inbox).

1. In [Google Cloud Console](https://console.cloud.google.com/), create or
   select a project.
2. Enable the **Gmail API** for that project (APIs & Services → Enable
   APIs and Services → search "Gmail API").
3. Configure the **OAuth consent screen**: choose "External," fill in the
   basics, and add your own Google account under "Test users" (this
   avoids needing Google's app-verification review for personal use).
4. Create **OAuth 2.0 credentials** of type **"Desktop app"** — this gives
   you a `client_id` and `client_secret`. You don't need to download or
   keep the credentials.json Google offers here; you'll only use the two
   values it displays.
5. Run the one-time local helper script to get a refresh token via your
   browser:
   ```bash
   pip install google-auth-oauthlib   # only needed for this one-time step
   python3 scripts/get_gmail_refresh_token.py <client_id> <client_secret>
   ```
   This opens a browser, asks you to approve `gmail.send` access, and
   prints three values: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`,
   `GMAIL_REFRESH_TOKEN`. These are the only Gmail credentials this
   project ever uses — there is no `credentials.json`/`token.json` file
   involved anywhere in the actual `jobsearch` package.
6. Store those three values as secrets — locally in `.env` for testing
   (never committed; see `.gitignore`), and later as GitHub Actions
   repository secrets once that layer is built.

The refresh token is long-lived (it doesn't expire from mere disuse) but
can be invalidated if you revoke access at
[myaccount.google.com/permissions](https://myaccount.google.com/permissions)
or change your Google account password — if sending starts failing with an
auth error, that's the first thing to check; re-run step 5 to get a new one.

## Required environment variables

In addition to the core-engine variables (`GREENHOUSE_BOARDS`, etc. — see
`.env.example`), the email layer needs:

| Variable | Required | Purpose |
|---|---|---|
| `GMAIL_CLIENT_ID` | yes | OAuth2 client ID from the Desktop app credentials |
| `GMAIL_CLIENT_SECRET` | yes | OAuth2 client secret |
| `GMAIL_REFRESH_TOKEN` | yes | Long-lived refresh token from the one-time script |
| `JOBSEARCH_RECIPIENT_EMAIL` | yes | Where the report gets sent — never hard-coded |
| `GMAIL_TOKEN_URI` | no | Override the OAuth token endpoint (default is Google's) |
| `JOBSEARCH_SENDER_EMAIL` | no | "From" header override (must be a verified alias on the sending account) |
| `JOBSEARCH_EMAIL_SUBJECT_PREFIX` | no | Prepended to every subject line, e.g. `"[JobBot] "` |

Missing any *required* variable raises a clear `GmailAuthConfigError` or
`EmailConfigError` (naming exactly which variable is missing) rather than
failing silently or with a confusing stack trace from deep inside a
Google library.

## Local testing instructions (email layer)

**Preview formatting with zero Gmail credentials needed** — the formatter
has no Gmail/network dependency at all:

```python
from jobsearch.engine import run_search
from jobsearch.config import Config
from jobsearch.email.formatter import format_search_result_email

result = run_search(Config.from_env())
html = format_search_result_email(result, candidate_years=4.0)
open("preview.html", "w").write(html)
# open preview.html in a browser to see exactly what the email will look like
```

**Send a real test email** once you have the Gmail env vars set:

```bash
export GMAIL_CLIENT_ID=...
export GMAIL_CLIENT_SECRET=...
export GMAIL_REFRESH_TOKEN=...
export JOBSEARCH_RECIPIENT_EMAIL=you@example.com

python3 -c "
from jobsearch.engine import run_search
from jobsearch.config import Config
from jobsearch.email.gmail_sender import send_search_result_email

result = run_search(Config.from_env())
response = send_search_result_email(result, candidate_years=4.0)
print('Sent:', response.get('id'))
"
```

If there are zero new jobs (e.g. no boards configured), this correctly
sends a short "no new matching jobs were found" email rather than
fabricating anything or silently doing nothing.

## GitHub Actions considerations (for when that layer is built)

Noting these now since they affect how the email layer was designed, even
though the workflow itself isn't built yet:

- Each of the four Gmail environment variables becomes a **repository
  secret** (Settings → Secrets and variables → Actions), referenced in the
  workflow as `${{ secrets.GMAIL_CLIENT_ID }}` etc. — never a plain
  "variable," since these are credentials.
- The refresh-token flow was chosen specifically because it's
  **stateless across CI runs**: there's no `token.json` to persist as a
  workflow artifact or cache between runs (which would itself become a
  secret-management problem). Every run authenticates fresh from the
  refresh token; the short-lived access token it exchanges for is never
  written anywhere.
- The workflow will need `pip install -e .` (the Gmail dependencies are
  already in core `dependencies`, not an optional extra, since sending
  email is now a first-class part of this project).
- Whatever script the orchestration layer runs should follow the order
  the requirements specify: **send the email, confirm it succeeded (check
  the Gmail API response), and only then call
  `SeenJobStore.mark_seen(...)`** — in that order, so a failed send never
  causes a job to be silently skipped in the next run.
- Never `echo` or `print` any of the four Gmail secret values in workflow
  logs (GitHub does mask registered secrets automatically, but avoid
  logging them regardless as defense in depth).

## Known limitations (current scope)

- Only Greenhouse and Lever are implemented. Companies using Workday,
  iCIMS, Ashby, LinkedIn, etc. aren't covered yet.
- Experience-requirement and sponsorship detection are regex/heuristic —
  they won't catch every phrasing a job posting might use, and should be
  treated as a first pass, not ground truth.
- Seen-job persistence exists (`JsonFileSeenJobStore`) but nothing calls
  `mark_seen()` yet — that's the orchestration layer's job, not built yet.
- No GitHub Actions workflow yet — scheduling, secret wiring, and the
  send-then-mark-seen orchestration are the next piece, not this one.
- Gmail sending requires a one-time interactive browser step locally to
  obtain the refresh token (`scripts/get_gmail_refresh_token.py`) — this
  can't be done headlessly in CI, by design (OAuth consent needs a human).
- This sandbox's outbound network is restricted to a small domain
  allowlist that doesn't include `boards-api.greenhouse.io`, `api.lever.co`,
  or Google's OAuth/Gmail endpoints, so live fetching and live email
  sending couldn't be verified end-to-end here. Both are fully unit-tested
  with mocked network calls, and the ATS-fetching path (at least) was
  separately confirmed working from the user's own machine.
