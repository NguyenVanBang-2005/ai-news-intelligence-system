# AI News Intelligence System

[![CI](https://github.com/NguyenVanBang-2005/ai-news-intelligence-system/actions/workflows/ci.yml/badge.svg)](https://github.com/NguyenVanBang-2005/ai-news-intelligence-system/actions/workflows/ci.yml)

## What it is

A backend and web UI that collects AI news and organises it:

- **Collection**: reads RSS/Atom feeds (optionally GNews searches), skips duplicate URLs.
- **Topics**: article embeddings + BERTopic, run as a manual batch with `POST /api/v1/ai/process`
  (nothing is re-clustered automatically).
- **Summaries**: extractive (sentences taken from the article).
- **Trending**: topics with more articles in the last hours than their usual rate.
- **Search**: hybrid semantic + keyword search over stored articles (`POST /api/v1/ai/search`).
- **LLM**: used only by `POST /api/v1/ai/ask`, which is optional and needs admin access.

**Architecture**: one FastAPI application, a layered monolith:
`routes -> services -> repositories -> models`. `app/services/` holds Python modules,
not separate services. There is one entry point (`app.main:app`); the UI is served by the
same process.

## Quick start A: run on the host with the evaluation snapshot (recommended for a demo)

The snapshot `local-data/ainis_eval_v2.db` (SQLite, 200 articles, topics already computed)
is **not in the repository** (`local-data/` is gitignored); the team sends it separately.
Put it at `local-data/ainis_eval_v2.db` and check it:

```bash
sha256sum local-data/ainis_eval_v2.db                                       # Git Bash
# PowerShell: (Get-FileHash local-data\ainis_eval_v2.db -Algorithm SHA256).Hash
# expected:   863acab642547abc9598617a88572ac2d207229a0650d1adae308b3c7e5bc708
```

**Do not run ingestion, `POST /ai/process` or "Rescan sources" on the original file**: they
change it. Copy it first and point `DATABASE_URL` at the copy if you want to try them.

Verified on Python 3.14.7 locally; Dockerfile and CI use 3.12. All commands run from the
repository root. *Creating the venv and `pip install` were not re-run for this release
(an existing venv was used).*

1. Create the virtual environment:

```bash
python -m venv .venv
```

2. Activate it:

```bash
source .venv/Scripts/activate        # Git Bash
```

```powershell
.\.venv\Scripts\Activate.ps1         # PowerShell
```

3. Install the dependencies (includes the ML libraries):

```bash
pip install -r requirements.txt
```

4. Run:

```bash
# Git Bash
DATABASE_URL="sqlite:///local-data/ainis_eval_v2.db" \
EMBEDDING_MODEL_NAME="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" \
HF_HUB_OFFLINE=1 AI_PRELOAD_MODEL=true \
uvicorn app.main:app --port 8000
```

```powershell
# PowerShell
$env:DATABASE_URL = "sqlite:///local-data/ainis_eval_v2.db"
$env:EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
$env:HF_HUB_OFFLINE = "1"
$env:AI_PRELOAD_MODEL = "true"
uvicorn app.main:app --port 8000
```

Then open <http://127.0.0.1:8000/>. Health: `GET /api/v1/health` returns
`{"status":"ok","model_ready":true}` once the model is loaded (`/health` without the prefix is 404).

Notes:

- `EMBEDDING_MODEL_NAME` must be the model above: the snapshot's embeddings and the search
  threshold were made with it. It is also the default in `app/core/config.py` and the value
  in `.env.example`; setting it here only makes the command independent of a local `.env`.
- `HF_HUB_OFFLINE=1` must be a real environment variable of the process. A line in `.env`
  is not enough: `.env` is read by the app's settings, not by the Hugging Face library.
  Offline mode needs the model already in the local Hugging Face cache; without it, the
  model is downloaded on first use (needs Internet).
- The first start takes about 30 seconds to import the ML libraries and load the model.
  `AI_PRELOAD_MODEL=true` does this in the background at startup, so the first search does
  not wait; without it the first search waits instead.
- Admin endpoints answer 503 until `ADMIN_API_TOKEN` is set (see Configuration).

## Quick start B: Docker Compose (PostgreSQL 17 + migrations + API)

```bash
cp .env.example .env      # then set POSTGRES_PASSWORD and ADMIN_API_TOKEN
docker compose up -d --build
```

- API and UI on <http://127.0.0.1:8001/> (`API_PORT`, default 8001). The DB is published on
  `127.0.0.1:${POSTGRES_PORT}` only through `compose.override.yaml` (local development).
- The image installs `requirements.txt`, so it **has the ML libraries**. The embedding model
  is **downloaded into the image at build time** (`docker compose up --build` needs Internet),
  in its own layer after `pip install` and before the app code is copied, into
  `HF_HOME=/opt/hf-cache`. The Dockerfile build argument `EMBEDDING_MODEL_NAME` picks the model
  (default: the same as the code). `compose.yaml` sets `HF_HUB_OFFLINE=1` unless you override
  it, so the running API never downloads a model.
- Create the first admin account (see [Accounts and roles](#accounts-and-roles)):
  `docker exec -it ainis_main-api-1 python scripts/create_admin.py --username <name>`
  (the container name depends on your Compose project name; see `docker compose ps`).
- A fresh stack has an **empty database**: no articles and no topics until you add sources,
  run ingestion (`POST /api/v1/ingestion/run`) and then `POST /api/v1/ai/process`.
- Database setup, backup and restore: [docs/database.md](docs/database.md).
- Last verified on 2026-10-27 at commit `229f9d0`
  ([postgres_backup_restore.txt](docs/evidence/postgres_backup_restore.txt): start, restart,
  backup, restore); fresh start also in [compose_fresh_start.txt](docs/evidence/compose_fresh_start.txt)
  (2026-10-24). **Not re-verified at the current main.**

## Configuration

Copy `.env.example` to `.env`. Values in the real environment override `.env`.
Never commit `.env`.

| Variable | `.env.example` | Meaning |
|---|---|---|
| `DATABASE_URL` | PostgreSQL on `127.0.0.1:5432` | Host runs only; inside Compose the URL is built from `POSTGRES_*` |
| `POSTGRES_PASSWORD` | placeholder `news` | Compose database password; the placeholder is for local development only, change it. If you change it and also run on the host with `DATABASE_URL`, change the password in `DATABASE_URL` too |
| `API_PORT` | `8001` | Host port of the Compose API |
| `ADMIN_API_TOKEN` | empty | Token for admin endpoints; empty means they answer 503. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `EMBEDDING_MODEL_NAME` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Embedding model (same as the code default); the snapshot and the search thresholds were made with it |
| `AI_PRELOAD_MODEL` | `true` | Load the model in the background at startup (code default `false`) |
| `AI_SEARCH_MIN_SIMILARITY` | `0.5` | Public search: an article below this is shown only if it contains at least half of the query's distinct words (common words ignored); tuned with the model above |
| `ASK_MIN_SIMILARITY` | `0.8` | Similarity floor for `/ai/ask` |
| `ASK_ALLOW_LINKS` | `false` | Whether `/ai/ask` accepts a link and downloads it (code default `true`) |
| `INGESTION_FULL_TEXT` | `false` | Download the article page when the feed gives only a short snippet (code default `true`) |
| `AI_SEARCH_RATE_PER_MINUTE` | `30` | Public search requests per client IP per minute, counted per process; over it: 429 with `Retry-After` |
| `AI_SEARCH_USER_RATE_PER_MINUTE` | `120` | Same, for signed-in users (user or admin), counted per account instead of per IP |
| `SESSION_COOKIE_SECURE` | `false` | Send the session cookie over HTTPS only; set `true` when served over HTTPS |
| `AI_SEARCH_MAX_BODY_BYTES` | `4096` | Largest accepted search request body |

The LLM for `/ai/ask` is any OpenAI-compatible API (`LLM_BASE_URL`, `LLM_MODEL`,
`LLM_API_KEY`); see the comments in `.env.example`.

## Using it

Web UI (same origin as the API, no build step):

- **Search** (`/`, `#/search`): hybrid search, trending chips, article detail drawer.
- **Topics** (`#/topics`): topic cards, a daily chart of trending topics, article list per topic.
- **Sources** (`#/sources`): read-only source list (name, type, language, sync status) and the
  latest classified articles.
- **API** (`/docs`): Swagger UI.
- **Log in / Register** (top right): a dialog; once signed in the bar shows the username, the
  role, "Change password" and "Log out", plus an **Admin** link for admins. There is no admin token input anywhere.
- **Admin** (`/admin/`, admin role only): source list with sync status, add an RSS/Atom source,
  turn a source on or off (Enable / Disable), delete a source (after a confirmation), run ingestion for all sources or one source, and
  start AI processing and follow the job until it finishes. Signed out, it says "Log in as an
  administrator"; a `user` account sees "Administrator role required".

All API paths are under `/api/v1`.

| Access | Endpoints |
|---|---|
| Public | `GET /health`, `GET /sources`, `GET /articles`, `GET /articles/{id}`, `GET /topics/trending`, `GET /topics/timeseries`, `GET /ai/topics`, `POST /ai/search` (rate limited) |
| Signed-in session (cookie; `X-Admin-Token` does not count) | `GET /auth/me`, `POST /auth/change-password` |
| Admin (`X-Admin-Token` or an admin session) | `POST /sources`, `PATCH /sources/{id}`, `DELETE /sources/{id}`, `POST /ingestion/run`, `POST /ai/process`, `GET /ai/process/{job_id}`, `POST /ai/ask` |

Without a signed-in session, admin endpoints answer **401** when the token is missing or
wrong, and **503** when the server has no `ADMIN_API_TOKEN`. Deleting a source also deletes
its articles.
UI-to-API details: [docs/ui-api-mapping.md](docs/ui-api-mapping.md).

## Accounts and roles

- Endpoints: `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`,
  `POST /auth/change-password`.
  Login sets an HttpOnly, `SameSite=Strict` session cookie (12 hours, `SESSION_TTL_HOURS`);
  the database keeps only a SHA-256 of the session token. Passwords are hashed with scrypt.
- Two roles: `user` and `admin`. Registration always creates a `user`; no API endpoint
  changes a role. An `admin` session can call the admin endpoints above; a `user` session
  gets 403 there.
- Create the first admin (or promote an existing account) with the script; it asks for the
  password twice without showing it (or reads `AINIS_NEW_ADMIN_PASSWORD`). An existing
  account keeps its password unless you add `--reset-password`.

  ```bash
  python scripts/create_admin.py --username <name>                               # host
  docker exec -it ainis_main-api-1 python scripts/create_admin.py --username <name>  # Docker
  ```

- `POST /auth/change-password` (session cookie, `X-Requested-With: ainis`) takes
  `{current_password, new_password}`; the new password follows the registration rules and must
  differ from the current one (422). A wrong current password is 400; after
  `AUTH_LOGIN_MAX_FAILURES` wrong tries per account it is 429. On success (204) the password is
  re-hashed and every other session of the account ends; the current one stays signed in.
- `X-Admin-Token` still works as a service key for scripts. When the header is present only
  the token is checked (cookies are ignored).
- With a session cookie, admin `POST`/`PATCH`/`DELETE` requests must send
  `X-Requested-With: ainis`, and an `Origin` header (if any) must match the host; otherwise 403.
- Search limit by role: anonymous 30 per minute per IP (`AI_SEARCH_RATE_PER_MINUTE`), signed-in
  users 120 per minute per account (`AI_SEARCH_USER_RATE_PER_MINUTE`).

## Evaluation

- Corpus ([eval_dataset_summary.txt](docs/evidence/eval_dataset_summary.txt)): 200 articles
  from 8 RSS feeds (2 more feeds were blocked by bot protection). After the topic
  configuration chosen on 2026-10-30 (HDBSCAN `min_cluster_size` capped at 8,
  `min_samples` 1): **10 topics, 35 outliers (17.5%)**.
- That configuration was **chosen on this same corpus**
  ([topic_param_experiment.txt](docs/evidence/topic_param_experiment.txt),
  [topic_robustness.txt](docs/evidence/topic_robustness.txt)), so these numbers are not an
  independent test.
- Quality protocol ([docs/evaluation-guide.md](docs/evaluation-guide.md)): a stratified
  sample of 50 articles (`scripts/export_corpus.py`), labeled by two people independently
  for topic correctness and summary quality; `scripts/score_corpus.py` reports percent
  agreement and Cohen's kappa.
- **No accuracy figures are reported yet**: the sample has not been labeled.

## Tests and CI

```bash
pip install -r requirements-dev.txt   # requirements.txt + pytest, pytest-cov, ruff
ruff check .
pytest -rs
```

PostgreSQL cases run only when `TEST_POSTGRES_ADMIN_URL` points to a **throwaway** PostgreSQL
server (each test creates and drops its own database); otherwise they are skipped.

Latest local run ([test_results_dee8d99.txt](docs/evidence/test_results_dee8d99.txt)),
2026-11-01, commit `dee8d99`, Windows, Python 3.14.7, SQLite only: `ruff check .` clean;
**689 passed, 215 skipped, 0 failed**. All 215 skips are PostgreSQL cases
(`TEST_POSTGRES_ADMIN_URL` not set).

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs on every push and pull
request: Ubuntu, Python 3.12, `pip install -r requirements-dev.txt`, `ruff check .`, and
`pytest -v -rs -o addopts=""` against a PostgreSQL 17 service. CI on GitHub also runs the
PostgreSQL tests.

## Known limitations

- Search, login and registration rate limits are in memory, per process: they are exact
  only with a single worker (several workers count separately).
- Registering a username that exists answers 409, so anyone can find out which usernames exist.
- With `SESSION_COOKIE_SECURE=false` (the default, for plain HTTP) the session cookie is also
  sent over unencrypted HTTP.
- No password recovery by email: a forgotten password can only be reset by an operator with
  `scripts/create_admin.py --reset-password` (which also makes the account an admin).
- No account management through the API (listing, disabling or changing the role of
  accounts); only `scripts/create_admin.py` creates or promotes admins.
- Two "Rescan sources" runs at the same time are not locked against each other.
- AI jobs run inside the API process; a restart loses a running job. At startup, jobs left
  pending or running are marked failed ("Interrupted by application restart"), so a new
  `POST /ai/process` can start at once instead of waiting out the 1-hour job timeout.
  This assumes a single worker process.
- `/docs` needs Internet (Swagger UI is loaded from a CDN); the main UI does not.
- No automatic backups.
- The PNG logo looks blurry on 2x screens.
- Topic labels mix heuristic names and BERTopic keywords.
- Topics partly follow the source (some feeds fall mostly into one topic).
- The topic configuration was chosen on the same corpus it is reported on.
- Public search shows at most 5 results (`ASK_MAX_SOURCES`, default 5).
- Search does no stemming ("centers" does not match "center").
- With a two-word query, one matching word is enough, so unrelated articles can appear.
- Articles found only by keyword can show a low similarity score.
- The UI was checked with automated tests in headless Microsoft Edge and manually in Brave;
  Firefox and Safari were not tested.
- Library versions are not pinned (ranges in `requirements*.txt`), and CI runs Python 3.12
  while the dev machine runs 3.14.7, so a test that passes on the dev machine may not pass in CI.
- "Rescan sources" with a real public RSS feed has not been tested from the browser (only
  through the API).
- Model loading takes time at startup (about 30 seconds on the dev machine).
- Two RSS sources (VentureBeat, AI News) block bots.
- The corpus is a one-day snapshot; ingesting again will not reproduce it. Its articles
  are older than the 24-hour trending window, so on the snapshot the trending chips are
  hidden and the Topics chart says no topic is trending.
- PostgreSQL is checked only by CI and by the backup/restore run of 2026-10-27.

## Reading the code

1. `app/main.py`: app, static UI, middleware.
2. `app/api/routes/`: HTTP endpoints.
3. `app/services/ingestion.py`: feeds to articles.
4. `app/services/analyzer.py`: keyword analysis and extractive summaries.
5. `app/services/topic_model.py`: embeddings + BERTopic batch.
6. `app/services/news_search.py` and `app/services/hybrid_search.py`: search.
