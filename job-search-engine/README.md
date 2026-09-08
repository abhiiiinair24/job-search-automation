# jobsearch — automated job-search engine, Gmail delivery, and scheduling

This project **discovers** job postings by searching for your target
roles (via the Adzuna job-search API — no company list to maintain),
optionally watches specific companies directly (Greenhouse/Lever), filters
and ranks everything against a candidate profile, emails the results via
the Gmail API, and — via a GitHub Actions workflow — runs on a schedule
and remembers what it already sent you, so you only ever hear about
genuinely new postings.

**Repository layout** (this matters for where files go — see "GitHub
Actions considerations" below):

```
job-search-automation/            <- git repo root
├── .github/workflows/job-search.yml    <- MUST live at repo root
└── job-search-engine/                   <- the actual Python package
    ├── config/boards.json                <- OPTIONAL direct-watch list
    ├── data/seen_jobs.json                <- persisted seen-job state
    ├── src/jobsearch/...
    └── tests/...
```

## Architecture

```
src/jobsearch/
  models.py            Job dataclass, SponsorshipStatus/SourceType enums,
                        stable_id (dedup key) and most_recent_date helpers
  config.py             Config dataclass, loaded from env vars (Adzuna
                         credentials + the optional boards config file)
  boards_config.py       BoardsConfig — loads config/boards.json (optional
                          direct-watch list); no code/CI changes needed to
                          edit it
  keyword_match.py        Word-boundary-safe keyword matching, shared by
                          ranking.py and filters/experience.py
  profile.py             CandidateProfile dataclass + default_profile() —
                          skills/roles/experience/preferred locations,
                          kept out of ranking.py
  seen_store.py           SeenJobStore abstraction (in-memory + JSON-backed)
                          for tracking which jobs have already been emailed
  sources/
    base.py             JobSource ABC + safe_fetch_jobs() error boundary
    adzuna.py             AdzunaDiscoverySource — PRIMARY discovery: searches
                          by target role, not by company (see below)
    enrichment.py           Best-effort Greenhouse/Lever enrichment of
                            Adzuna-discovered jobs (cleaner URL/description
                            when a confident match is found; never required)
    greenhouse.py        Greenhouse public job-board API integration
                          (direct-watch, optional)
    lever.py             Lever public postings API integration
                          (direct-watch, optional)
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
  cli.py                  argparse CLI, prints a formatted report (no email,
                          no seen-tracking side effects - just search+print)
  orchestrator.py          Ties everything together for a scheduled run:
                           run_search -> send email -> CONFIRM success ->
                           THEN mark_seen. This is what GitHub Actions runs.
  email/
    formatter.py           Pure HTML rendering of a SearchResult - no
                            Gmail/network imports, fully unit-testable
    config.py               EmailConfig (recipient etc.) loaded from env vars
    gmail_auth.py            OAuth2 credential loading from env vars/secrets
                             (no credential files read or written)
    gmail_sender.py           Sends via the Gmail API (not SMTP); the only
                             module in the project that makes Gmail network
                             calls

config/
  boards.json             OPTIONAL editable list of Greenhouse boards /
                          Lever companies to also always watch directly —
                          NOT required; Adzuna discovery works standalone
data/
  seen_jobs.json           Persisted "already emailed" job ids, committed
                          back to the repo by the GitHub Actions workflow

scripts/
  get_gmail_refresh_token.py  One-time LOCAL script (not part of the
                              package) to obtain a Gmail refresh token via
                              browser OAuth consent

.github/workflows/
  job-search.yml           Scheduled + manually-triggerable GitHub Actions
                           workflow (repo-root level, NOT inside
                           job-search-engine/ - see below)

tests/                   312 unit/integration tests, no real network calls
```

### Design decisions worth knowing about

- **Sources are public, read-only APIs, no auth required.** Greenhouse
  (`boards-api.greenhouse.io`) and Lever (`api.lever.co`) both expose public
  JSON endpoints keyed by a company's board token/slug.
- **Stable IDs for dedup and seen-tracking:** `f"{source}:{native_job_id}"`
  (e.g. `greenhouse:4821093`). A hash-based fallback exists for the rare
  case a source doesn't expose a native id.
- **Experience filtering is soft-first, hard-second:** only jobs that
  explicitly state a minimum of 6+ years are hard-excluded; new-grad
  postings pass the filter but are penalized in *ranking* instead.
- **Experience extraction distinguishes overall vs. tech-specific
  mentions.** "3+ years of Python experience and 7+ years of engineering
  experience" correctly resolves to an overall requirement of 7, not 3 —
  each years-mention is scoped to its own clause and classified as general
  vs. tied to a named technology; a general mention always wins.
- **Skill/title/domain matching is word-boundary aware**, not plain
  substring search (`keyword_match.py`) — "rag" only matches the whole
  word "RAG," never as a substring of "average," "storage," or "leverage."
- **Preferred-location prioritization (e.g. Buffalo, NY).**
  `CandidateProfile.preferred_locations` is a hard priority tier in
  `rank_jobs()`: every matching job sorts ahead of every non-matching job,
  regardless of fit score.
- **Candidate profile lives in `profile.py`, not `ranking.py`** — a plain
  `CandidateProfile` dataclass that `ranking.py` consumes as input, so
  updating the profile never means editing scoring code.
- **Seen-job tracking is a pluggable abstraction** (`seen_store.py`):
  `InMemorySeenJobStore` for tests/one-off runs, `JsonFileSeenJobStore` for
  real persistence. Read failures (missing/corrupt file) are treated
  leniently as "nothing seen yet"; **write failures raise
  `SeenJobStoreWriteError`** rather than being silently swallowed, because
  a failed write would otherwise cause the same jobs to be re-emailed
  every subsequent run.
- **Gmail delivery is three separately-testable modules:** `formatter.py`
  (pure functions, zero Gmail imports), `gmail_auth.py` (OAuth2 credential
  loading from env vars, no credential files ever read/written), and
  `gmail_sender.py` (the only module making real Gmail API calls).
- **The orchestrator is the one place that decides ordering.**
  `orchestrator.run_scheduled_search()` calls `run_search()`, then sends
  the email, and **only after that call returns successfully** does it
  call `seen_store.mark_seen(...)`. A Gmail failure, an invalid
  config/credential, or a seen-store write failure all raise
  `OrchestrationError` and stop before anything gets marked as seen.
- **Board/company configuration (Greenhouse/Lever) is OPTIONAL, in a
  plain JSON file** (`config/boards.json`), not required for the system
  to find anything — `Config.from_env()` reads it automatically whenever
  `GREENHOUSE_BOARDS`/`LEVER_COMPANIES` env vars aren't explicitly set,
  but discovery (below) works with zero entries in this file.
- **Adzuna is the PRIMARY discovery mechanism** (`sources/adzuna.py`) —
  it searches by target role/keyword (derived from
  `CandidateProfile.target_roles` unless overridden), not by company, so
  no company list needs to be maintained anywhere for the system to find
  new employers. Greenhouse/Lever remain fully supported as an *optional*
  direct-watch addition on top of discovery, never a requirement. Adzuna
  does **not** provide complete US job-market coverage — it's one
  aggregator among several; treat it as a broad, free sample. See "Job
  discovery via Adzuna" below for setup, quota math, and this tradeoff in
  more depth.
- **Greenhouse/Lever enrichment of Adzuna results is best-effort and
  conservative** (`sources/enrichment.py`): for each company Adzuna
  surfaces (capped per run), a couple of plausible board-slug guesses are
  tried against both APIs, and a posting is only swapped in when its
  title matches *exactly* after normalization — no fuzzy/partial matches,
  to avoid conflating two different roles at the same company. Enrichment
  failing or being skipped never drops the job; Adzuna's own URL and
  description remain the fallback.
- **The GitHub Actions schedule uses a runtime local-time guard** to
  approximate America/New_York 8am/8pm despite GitHub cron being UTC-only
  and DST-unaware — see "How the scheduled workflow works" below.
- **Sponsorship and experience detection are heuristic, not ground
  truth** — always double check anything you're relying on directly on
  the actual posting.
- **Every fetch is wrapped in a try/except boundary** (`safe_fetch_jobs`)
  so one broken/unreachable source never crashes the whole run.

## Local setup (complete)

```bash
cd job-search-engine
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
nano .env   # fill in the values described below
export $(grep -v '^#' .env | xargs)   # load them into your shell
```

**Search only, no email** (prints to the terminal, makes no Gmail calls,
no seen-tracking side effects):

```bash
python3 -m jobsearch.cli --limit 15 --top 4
```

By default this reads target roles from your candidate profile and
searches Adzuna for them (see "Job discovery via Adzuna" below), plus any
companies listed in `config/boards.json` (optional). `GREENHOUSE_BOARDS`/
`LEVER_COMPANIES` env vars still work if you want a one-off override of
the boards file.

**Full scheduled-style run** (search + email + mark-seen — the same thing
the GitHub Actions workflow runs):

```bash
python3 -m jobsearch.orchestrator
```

This requires the Gmail environment variables below to be set. It's safe
to run repeatedly: jobs already marked seen (in `data/seen_jobs.json`)
won't be re-emailed.

## Job discovery via Adzuna (one-time setup)

This is what makes the system find companies you never named. Adzuna is
a real job-search API — you search by role/keyword, not by company — with
a genuine free tier, and **"personal research" is an explicitly permitted
use case** in its API Terms of Service (this project's use qualifies).

1. Go to [developer.adzuna.com](https://developer.adzuna.com/) and
   register — self-service, instant, no approval wait.
2. You'll get an **App ID** and **App Key** immediately. Add them to
   `.env` as `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` (and later as GitHub
   Actions secrets — see below).
3. That's it — no further setup. By default, search terms are pulled
   automatically from your candidate profile's target roles
   (`profile.py`), so there's nothing to enumerate or maintain.

**What this does and doesn't give you:**
- Searches are US-only (`/v1/api/jobs/us/search`) and scoped to postings
  created within `ADZUNA_MAX_DAYS_OLD` (default 4) — both align with the
  existing recency/location filters, which still run afterward as a
  second check.
- Adzuna's own listing includes a `redirect_url` (works, but routes
  through Adzuna rather than being the company's own link) and a
  *truncated* description. The enrichment step (`sources/enrichment.py`)
  tries to replace both with a cleaner Greenhouse/Lever direct link when
  it can confidently match the posting — see the design-decisions bullet
  above for exactly how conservative that match has to be.
- **Adzuna does not index the entire US job market.** It's a broad,
  genuinely free aggregator, not an authoritative or exhaustive source —
  some companies (especially ones that only post to their own
  Greenhouse/Lever board and nowhere else) may never surface via Adzuna
  at all. Direct-watch (`config/boards.json`) remains available exactly
  for that gap, on a per-company basis.

**Free-tier quota, and how this project stays inside it:** Adzuna's
documented limits are 25/min, 250/day, 1,000/week, 2,500/month. This
project issues one Adzuna API call per target role per run (8 roles by
default) — roughly 16 calls/day at the twice-daily schedule, ~480/month —
comfortably inside every one of those ceilings, with real headroom for
retries. `ADZUNA_RESULTS_PER_PAGE` (default 25) and
`ADZUNA_ENRICHMENT_MAX_COMPANIES` (default 20, and this only counts
against Greenhouse/Lever, not Adzuna's own quota) keep this modest by
design — raise them only with the quota math above in mind.

## Gmail API setup (one-time)

The email layer uses the **Gmail API directly (OAuth2), not SMTP**, with
a narrow `gmail.send`-only scope (this app can never read your inbox).

1. In [Google Cloud Console](https://console.cloud.google.com/), create or
   select a project. (The "$300 free credit" banner is unrelated — the
   Gmail API itself is free and needs no billing account.)
2. Enable the **Gmail API** for that project (APIs & Services → Enable
   APIs and Services → search "Gmail API" → Enable).
3. Configure the **OAuth consent screen** (APIs & Services → OAuth
   consent screen): choose **External**, fill in app name + your email,
   and — this step is easy to miss — add your own Google account under
   **Audience → Test users**. An unverified app refuses to authorize
   anyone not on this list.
4. Create **OAuth 2.0 credentials** (APIs & Services → Credentials → "+
   Create Credentials" → OAuth client ID) of type **Desktop app**. This
   gives you a Client ID and Client Secret.
5. Run the one-time local helper script to get a refresh token via your
   browser:
   ```bash
   pip install google-auth-oauthlib   # only needed for this one-time step
   python3 scripts/get_gmail_refresh_token.py <client_id> <client_secret>
   ```
   This opens a browser, asks you to approve `gmail.send` access, and
   prints three values to store as secrets. There is no
   `credentials.json`/`token.json` file involved anywhere in the actual
   `jobsearch` package — only these three values matter.
6. Store those values in your local `.env` (never committed), and later
   as GitHub Actions repository secrets (see below).

The refresh token is long-lived but can be invalidated by revoking access
at [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
or changing your Google account password — if sending starts failing with
an auth error, that's the first thing to check; re-run step 5 for a new one.

## Required environment variables / GitHub Actions secrets

| Variable | Required | Where it's used | Purpose |
|---|---|---|---|
| `ADZUNA_APP_ID` | yes* | secret | Adzuna App ID — free signup at developer.adzuna.com |
| `ADZUNA_APP_KEY` | yes* | secret | Adzuna App Key |
| `GMAIL_CLIENT_ID` | yes | secret | OAuth2 client ID from the Desktop app credentials |
| `GMAIL_CLIENT_SECRET` | yes | secret | OAuth2 client secret |
| `GMAIL_REFRESH_TOKEN` | yes | secret | Long-lived refresh token from the one-time script |
| `JOBSEARCH_RECIPIENT_EMAIL` | yes | secret | Where the report gets sent — never hard-coded |
| `ADZUNA_SEARCH_TERMS` | no | env | Override the target-role-derived default search terms |
| `ADZUNA_MAX_DAYS_OLD` | no | env | Adzuna-side recency filter (default 4, matches `RECENCY_DAYS`) |
| `ADZUNA_RESULTS_PER_PAGE` | no | env | Results per search term (default 25 — keep modest, see quota math) |
| `ADZUNA_ENRICH` | no | env | Enable/disable Greenhouse/Lever enrichment (default true) |
| `ADZUNA_ENRICHMENT_MAX_COMPANIES` | no | env | Cap on companies enriched per run (default 20) |
| `GMAIL_TOKEN_URI` | no | env | Override the OAuth token endpoint (default is Google's) |
| `JOBSEARCH_SENDER_EMAIL` | no | secret (optional) | "From" header override (must be a verified alias on the sending account) |
| `JOBSEARCH_EMAIL_SUBJECT_PREFIX` | no | env | Prepended to every subject line, e.g. `"[JobBot] "` |
| `GREENHOUSE_BOARDS` / `LEVER_COMPANIES` | no | env | Optional direct-watch override of `config/boards.json` — leave unset in CI |
| `BOARDS_CONFIG_PATH` | no | env | Override the boards-file path (default `config/boards.json`) |
| `RECENCY_DAYS`, `HARD_EXCLUDE_EXPERIENCE_YEARS`, `CANDIDATE_EXPERIENCE_YEARS`, `RESULTS_LIMIT`, `SEEN_STORE_PATH`, `LOG_LEVEL` | no | env | Core engine tuning — see `.env.example` |

\* Without `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`, discovery is simply disabled
(logged, not a crash) — the system falls back to direct-watch only
(`config/boards.json`), which defeats the "no company list to maintain"
goal. The GitHub Actions workflow treats these as required and fails
clearly if either is missing, since discovery is the whole point of the
automation; the underlying library code degrades gracefully for other
use cases (e.g. local testing with only Greenhouse/Lever configured).

**Locally**, all of these go in `.env` (gitignored).

**In GitHub Actions**, the seven variables marked "secret" above (six
required plus the optional `JOBSEARCH_SENDER_EMAIL`) must be
**repository secrets** (Settings → Secrets and variables → Actions →
"New repository secret"), never repository *variables* and never
committed anywhere. The workflow references them as `${{ secrets.X }}`.

Missing any required variable raises a clear, specific
`GmailAuthConfigError` or `EmailConfigError` naming exactly what's
missing — both locally and in the Actions log — rather than a confusing
stack trace or silent no-op.

## Adding and removing direct-watch Greenhouse/Lever companies (optional)

This is **not required** — Adzuna discovery (above) works with an empty
`config/boards.json`. Use this only if you want to *always* watch a
specific company regardless of whether Adzuna happens to surface it.

Edit `job-search-engine/config/boards.json` — no code changes, no
workflow changes, just commit the edit:

```json
{
  "greenhouse_boards": ["stripe", "airbnb"],
  "lever_companies": ["netflix"]
}
```

- A Greenhouse board token is the slug in `https://boards.greenhouse.io/<token>`.
- A Lever company slug is the one in `https://jobs.lever.co/<slug>`.
- Not every company uses Greenhouse or Lever — only those two ATS
  platforms are integrated currently.
- After committing a change here, the *next* scheduled run (or a manual
  `workflow_dispatch`) picks it up automatically — no other changes needed.

## How the scheduled workflow works

`.github/workflows/job-search.yml` runs on a schedule and supports manual
triggering. Two things about it are worth understanding:

**Timezone/DST handling.** GitHub Actions `schedule:` cron always runs in
UTC and has no timezone concept. 8:00 AM / 8:00 PM America/New_York shifts
between UTC-4 (EDT, roughly March–November) and UTC-5 (EST, the rest of
the year), so the workflow schedules **four** cron entries — both times at
both possible offsets, each at `:07` past the hour rather than exactly on
it (GitHub's own guidance: on-the-hour jobs face the most platform-wide
queue contention, since everyone else's cron jobs fire then too). A
runtime guard step checks the actual current `America/New_York` clock and
runs only if it's within 45 minutes of 8:00am or 8:00pm locally — a
minute-precision tolerance window, not just an hour match, chosen to stay
safely under the 60-minute gap to the *other* (wrong-season) entry's
target, so the two candidate firings per target time never both pass. In
practice this means one of the two candidate cron firings per target time
runs the real job each day; the other exits immediately as a no-op. This
avoids needing to hand-maintain a DST cutover date in the workflow.
Neither the offset nor the tolerance window guarantees on-time execution —
GitHub documents that scheduled workflows can occasionally be delayed
substantially (hours, not just minutes) during high platform load; a
delay that large will still correctly result in a skipped run rather than
firing at the wrong local time.

**Send-then-mark-seen ordering.** The workflow's "Run job search and send
email" step invokes `python3 -m jobsearch.orchestrator` — the *same*
orchestrator module used locally — which internally runs the search,
sends the email, and only marks jobs as seen after Gmail confirms
success. If that step fails for any reason (bad credentials, Gmail
outage, a state-write failure), the workflow step fails with a non-zero
exit code and the "Commit updated seen-job state" step never runs, so
nothing is silently lost or double-counted.

**Persistence.** `data/seen_jobs.json` is committed back to the repo by
the workflow's last step, using the automatically-provided `GITHUB_TOKEN`
(the workflow's `permissions: contents: write` is the only permission it
requests). This is what makes "seen" state survive between runs on
GitHub's ephemeral runners — each run starts with a fresh VM, but
`actions/checkout` pulls the last-committed `seen_jobs.json` from git.

## How to manually trigger the workflow

1. Go to your repo on GitHub → **Actions** tab.
2. Select **"Job Search"** in the left sidebar.
3. Click **"Run workflow"** → select the branch → **"Run workflow"**.

A manual trigger (`workflow_dispatch`) always runs regardless of the
current time — the local-time guard only applies to scheduled cron
firings.

## Security considerations

- **Never commit**: `.env`, `credentials.json`, `token.json`, any
  `client_secret*.json`, or any real Gmail client ID/secret/refresh token.
  `.gitignore` covers all of these defensively, even though this project
  never creates credential *files* itself (everything is env-var based).
- **Gmail credentials only ever come from environment variables /
  GitHub Actions secrets** — `gmail_auth.py` has no code path that reads
  or writes a credential file.
- **The Gmail OAuth scope is `gmail.send` only** — this app cannot read,
  search, or delete anything in your inbox, even if the refresh token
  were somehow exposed.
- **The workflow requests only `contents: write`** — no `actions`,
  `packages`, `issues`, or other permissions, since committing
  `data/seen_jobs.json` is the only thing it needs to do.
- **Secrets are never echoed to logs.** The "verify required secrets"
  step in the workflow only prints which *names* are missing, never any
  value; GitHub also automatically masks registered secret values in logs
  regardless.
- If you ever suspect a credential was exposed, revoke it at
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
  (for the refresh token) or regenerate the client secret in Google Cloud
  Console (Credentials → your OAuth client → Reset Secret), then update
  the GitHub secret and re-run `scripts/get_gmail_refresh_token.py`.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `GmailAuthConfigError: Missing required...` | One of `GMAIL_CLIENT_ID`/`GMAIL_CLIENT_SECRET`/`GMAIL_REFRESH_TOKEN` isn't set. Locally: check `.env` and that you `export`ed it. In Actions: check the repository secret exists and is spelled exactly right. |
| `EmailConfigError: JOBSEARCH_RECIPIENT_EMAIL is not set` | Same idea — set that secret/env var. |
| Log says "ADZUNA_APP_ID/ADZUNA_APP_KEY not configured - job discovery is disabled" | Expected if you haven't set them — the run falls back to direct-watch only (`config/boards.json`), which is usually not what you want. Sign up free at developer.adzuna.com and set both. |
| Gmail send fails with an auth error | The refresh token may have been revoked (password change, manual revocation at myaccount.google.com/permissions, or the OAuth consent screen falling out of "Testing" test-user list). Re-run `scripts/get_gmail_refresh_token.py` and update the secret. |
| Workflow runs but does nothing (no error) | Check the "Check scheduled run time" step's log — if the current `America/New_York` time wasn't within 45 minutes of 8:00am/8:00pm, that's by design (see DST handling above). A very large gap (hours) usually means GitHub delayed that particular scheduled run substantially — the *other* seasonal cron entry, or the next scheduled time, should still fire normally. Use `workflow_dispatch` to force a real run regardless of time. |
| Same jobs emailed twice | Check whether `data/seen_jobs.json` actually got committed after the previous run (look at the "Commit updated seen-job state" step) — if that step didn't run (e.g. the email step failed), the previous run's jobs were correctly *not* marked seen and will legitimately reappear until a send succeeds. |
| Workflow can't push the updated seen-job file | Confirm `permissions: contents: write` is present in the workflow (it fails clearly with a permissions error otherwise) and that branch protection rules (if any) allow the `GITHUB_TOKEN` to push directly. |
| Local `python3 -m jobsearch.orchestrator` finds 0 new jobs | First check `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` are set (discovery is silently disabled without them — see the row above). If they are set, an empty result with no error is often legitimately "no matches right now" for your target roles within the recency window; also check `config/boards.json` if you're relying on direct-watch for a specific company. |
| `pip install -e ".[dev]"` fails | Confirm you're on Python 3.12+ (`python3 --version`) and inside an activated virtualenv. |

## Running the tests

```bash
python3 -m pytest -v          # verbose
python3 -m pytest --cov=jobsearch --cov-report=term-missing   # with coverage
```

All network calls are mocked (`requests.get` for job sources,
`googleapiclient.discovery.build` for Gmail) — the suite is fully offline
and deterministic, including the orchestrator and workflow-YAML tests.

## Local testing instructions (email/orchestration layer)

**Preview formatting with zero Gmail credentials needed:**

```python
from jobsearch.engine import run_search
from jobsearch.config import Config
from jobsearch.email.formatter import format_search_result_email

result = run_search(Config.from_env())
html = format_search_result_email(result, candidate_years=4.0)
open("preview.html", "w").write(html)
# open preview.html in a browser
```

**Send a real test email** (formatter + Gmail, no seen-tracking):

```bash
python3 -c "
from jobsearch.engine import run_search
from jobsearch.config import Config
from jobsearch.email.gmail_sender import send_search_result_email

result = run_search(Config.from_env())
response = send_search_result_email(result, candidate_years=4.0)
print('Sent:', response.get('id'))
"
```

**Run the full orchestrated flow locally** (search + email + mark-seen —
exactly what CI runs):

```bash
python3 -m jobsearch.orchestrator
```

If there are zero new jobs, this correctly sends a short "no new matching
jobs were found" email and marks nothing as seen — nothing is fabricated.

## Known limitations (current scope)

- **Adzuna does not provide complete coverage of the US job market.** It's
  one free aggregator among several; a company that only posts to its own
  Greenhouse/Lever board (and isn't picked up by Adzuna's own indexing)
  can be missed entirely. Direct-watch (`config/boards.json`) is the
  mitigation for a specific known gap, not a general fix.
- **Greenhouse/Lever enrichment is a heuristic, best-effort guess.**
  Slug-guessing from a company's display name won't always resolve
  (many real slugs aren't derivable from the name Adzuna shows), and even
  when a board is found, only an exact title match after normalization
  is trusted — a real but differently-worded posting at that same company
  won't be enriched. Neither failure mode drops the job; it just stays
  exactly as Adzuna reported it.
- Only Greenhouse and Lever are supported for direct-watch/enrichment.
- Experience-requirement and sponsorship detection are regex/heuristic —
  treat as a first pass, not ground truth.
- The DST-handling approach (four cron entries + a runtime hour guard)
  means the workflow *fires* up to 4x/day even though it only does real
  work twice — the no-op runs are cheap and fast but do consume a small
  amount of Actions minutes/log noise.
- This sandbox's outbound network is restricted to a small domain
  allowlist that doesn't include the ATS APIs, Adzuna, or Google's
  OAuth/Gmail endpoints, so live fetching/discovery/email sending
  couldn't be re-verified end-to-end from inside this environment on this
  pass — Greenhouse fetching and Gmail sending were both previously
  confirmed working from the user's own machine, and everything here
  (including Adzuna and enrichment) is covered by mocked unit/integration
  tests.
- The orchestrator and workflow have not yet been exercised inside actual
  GitHub Actions infrastructure with the new Adzuna discovery layer
  specifically — the earlier Gmail-only version was confirmed working in
  real GitHub Actions; a fresh manually-dispatched run after this change
  is the remaining end-to-end check.
