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

**Docker Compose ([Quick start B](#quick-start-b-docker-compose-main-path)) is the main way to run
the system; running on the host with SQLite (Quick start A) is the development path.**

## Quick start A (development): run on the host with the evaluation snapshot

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
- The admin page uses an admin session (create one with `scripts/create_admin.py`, see
  [Accounts and roles](#accounts-and-roles)). `ADMIN_API_TOKEN` is optional: it is only
  needed to call admin endpoints from scripts or curl (`X-Admin-Token`).

## Quick start B: Docker Compose (main path)

Needs Docker with Compose v2. From the repository root:

```bash
cp .env.example .env                    # 1. then set the values below
docker compose up -d --build            # 2. db -> migrate -> api
docker compose exec api python scripts/create_admin.py --username admin   # 3.
docker compose exec api python scripts/seed_demo.py                       # 4.
```

5. Open <http://127.0.0.1:8001/> (Search, Topics, trending) and log in as `admin` for `/admin/`.

`.env` values to set before step 2:

| Variable | Why |
|---|---|
| `POSTGRES_PASSWORD` | Database password. The `.env.example` value `news` is a placeholder: the stack starts with it, but set your own. Set it **before the first start**: the database keeps the password it was created with, so changing it later makes `migrate` and `api` fail to connect (see [docs/database.md](docs/database.md)) |

Nothing else is required. Optional: `API_PORT` if 8001 is taken; `NEWS_API_KEY` only for
`news_api` sources (the demo uses RSS); `LLM_*` only for `POST /ai/ask` (inside the container
`localhost` is the container itself, so a host Ollama is not reached at the default URL).

Step by step:

- **Step 2, first build needs Internet and disk space** (Python packages and the embedding
  model, which is baked into the image under `HF_HOME=/opt/hf-cache`; the running API sets
  `HF_HUB_OFFLINE=1` and never downloads a model). The image is about 11.1 GB on disk
  (3.83 GB content); see [Measured run](#measured-run-clean-clone) for times. Check with
  `docker compose ps`: `migrate` exited (0), `api` healthy.
- **If the build stops with a network error** while downloading packages (seen once:
  `failed to receive status: rpc error ... EOF` while downloading `nvidia_cudnn`), run the
  same command again; Docker continues from the layers it already has.
- **Step 3** uses the service name `api`, so it works whatever the Compose project (folder)
  name is. The script asks for the password twice without showing it; nothing is stored
  in code, migrations or compose files. Without a terminal (CI, or Git Bash printing
  "the input device is not a TTY"), pass it through `AINIS_NEW_ADMIN_PASSWORD` instead:

  ```bash
  read -rs -p "Admin password: " AINIS_NEW_ADMIN_PASSWORD; echo; export AINIS_NEW_ADMIN_PASSWORD
  docker compose exec -T -e AINIS_NEW_ADMIN_PASSWORD api python scripts/create_admin.py --username admin
  unset AINIS_NEW_ADMIN_PASSWORD
  ```

- **Step 4** (`scripts/seed_demo.py`, needs Internet, no API key, no admin login) adds four
  public RSS feeds, ingests them and runs AI processing (topics, embeddings) inside the
  container. Running it again adds nothing twice. One failing feed is reported and skipped;
  if every feed fails it exits with code 2 (most likely no Internet access).
- **Trending** counts articles of the last 24 hours. Just before a presentation, fetch
  fresh articles: `docker compose exec api python scripts/seed_demo.py --refresh`. If the
  last 24 hours still have no trending topic, the UI asks for the last 7 days instead and
  says so ("No trending topics in the last 24 hours. Showing the last 7 days.").
- `docker compose down` keeps the data; **`docker compose down -v` deletes the database**
  (articles, topics and the admin account). The model stays in the image.
- The database has no host port. For host-side Python (tests, alembic) publish it on
  `127.0.0.1:${POSTGRES_PORT}` with the development file:
  `docker compose -f compose.yaml -f compose.dev.yaml up -d`.
- The Compose API uses the session cookie `ainis_session_docker` (`SESSION_COOKIE_NAME` in
  `compose.yaml`), the host run `ainis_session`: browsers share cookies across the ports
  of one host, so with two names a Docker and a host server can run side by side without
  overwriting each other's sign-in.
- Database setup, backup and restore: [docs/database.md](docs/database.md).
- Older evidence: start, restart, backup and restore on 2026-10-27 at commit `229f9d0`
  ([postgres_backup_restore.txt](docs/evidence/postgres_backup_restore.txt)); earlier
  builds of about 20 minutes ([compose_fresh_start.txt](docs/evidence/compose_fresh_start.txt),
  2026-10-24) and about 32 minutes, with a 458 MB model cache in the image
  ([fresh_stack_startup_cleanup_abd974a.txt](docs/evidence/fresh_stack_startup_cleanup_abd974a.txt),
  2026-11-08).

### Measured run (clean clone)

Steps 1-4 above were run end to end on a clean clone at commit `3582c85` on 2026-11-11
(Windows 11, Docker 29.8.0, Compose v5.5.1):
[docker_clean_clone_3582c85.txt](docs/evidence/docker_clean_clone_3582c85.txt). To run
beside other stacks, every command had `-p <project>` and an extra file that moved the API
to another host port; nothing else differed. The admin was created with the
`AINIS_NEW_ADMIN_PASSWORD` path.

| Step | Measured |
|---|---|
| `up -d --build` (base image `python:3.12-slim` already in the Docker cache) | about 17 minutes (1031 s): `pip install` about 754 s, model download about 77 s, image export about 187 s |
| Image size | about 11.1 GB on disk, 3.83 GB content |
| API start to `model_ready: true` | about 14 s |
| `seed_demo.py` | about 52 s: 4 of 4 feeds, 101 articles, all 101 AI-processed, 2 topics |
| `seed_demo.py --refresh` right after | 3 s, no new articles, still 4 sources (nothing added twice) |
| `docker compose restart api` to `model_ready: true` | about 11 s; the existing login stayed valid |
| API memory after the seed | 2.07 GiB |

Also checked in that run: log in, `GET /auth/me` (role admin), wrong password (401),
admin endpoints without a session (401), `/` and `/admin/` (200, with CSP,
`X-Frame-Options: DENY`, `nosniff`), trending in the last 24 hours (2 topics), and that
the database has no host port.

Not measured: a build with an empty Docker cache; typing the admin password at the
interactive prompt; the UI in a browser; the README commands exactly as written, without
`-p` and the port file.

## Configuration

Copy `.env.example` to `.env`. Values in the real environment override `.env`.
Never commit `.env`.

| Variable | `.env.example` | Meaning |
|---|---|---|
| `DATABASE_URL` | PostgreSQL on `127.0.0.1:5432` | Host runs only; inside Compose the URL is built from `POSTGRES_*` |
| `POSTGRES_PASSWORD` | placeholder `news` | Compose database password; the placeholder is for local development only, change it. If you change it and also run on the host with `DATABASE_URL`, change the password in `DATABASE_URL` too |
| `API_PORT` | `8001` | Host port of the Compose API |
| `POSTGRES_PORT` | `5432` | Host port of the database, used only with `compose.dev.yaml` (inside Compose the API always uses 5432) |
| `ADMIN_API_TOKEN` | empty | Optional service key for admin endpoints from scripts/curl (`X-Admin-Token`); the UI uses an admin session instead. Empty: a request that sends the header gets 503. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `EMBEDDING_MODEL_NAME` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Embedding model (same as the code default); the snapshot and the search thresholds were made with it |
| `AI_PRELOAD_MODEL` | `true` | Load the model in the background at startup (code default `false`) |
| `AI_SEARCH_MIN_SIMILARITY` | `0.5` | Public search: an article below this is shown only if it contains at least half of the query's distinct words (common words ignored); tuned with the model above |
| `ASK_MIN_SIMILARITY` | `0.8` | Similarity floor for `/ai/ask` |
| `ASK_ALLOW_LINKS` | `false` | Whether `/ai/ask` accepts a link and downloads it (code default `true`) |
| `INGESTION_FULL_TEXT` | `false` | Download the article page when the feed gives only a short snippet (code default `true`) |
| `AI_SEARCH_RATE_PER_MINUTE` | `30` | Public search requests per client IP per minute, counted per process; over it: 429 with `Retry-After` |
| `AI_SEARCH_USER_RATE_PER_MINUTE` | `120` | Same, for signed-in users (user or admin), counted per account instead of per IP |
| `LOGIN_IP_MAX_ATTEMPTS`, `LOGIN_IP_WINDOW_SECONDS` | `20`, `60` | Login attempts (right or wrong, any username) per client address per window, counted per process before the password is checked; over it: 429 with `Retry-After` |
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

Without a signed-in session (none, expired or ended), admin endpoints answer **401**
"Not signed in.". A request that sends `X-Admin-Token` gets **401** when the token is
wrong and **503** when the server has no `ADMIN_API_TOKEN`. Deleting a source also deletes
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
- Create the first admin with the script; it asks for the password twice without showing it
  (or reads `AINIS_NEW_ADMIN_PASSWORD`). It first prints the database it writes to
  (`Database: ...`, password masked): check it is the one your server uses (`DATABASE_URL`).
  For an account that already exists:
  - `--reset-password` sets a new password and ends all its sessions; the role and the
    active flag stay as they are (a `user` stays a `user`).
  - `--promote` makes it an active `admin`; the password stays unless you add
    `--reset-password` too.
  - Without either flag the script stops with an error and changes nothing.

  ```bash
  python scripts/create_admin.py --username <name>                               # host
  python scripts/create_admin.py --username <name> --reset-password              # forgotten password
  python scripts/create_admin.py --username <name> --promote                     # existing account -> admin
  docker compose exec api python scripts/create_admin.py --username <name>          # Docker (service name)
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
- System figures from the Docker run of 2026-11-11
  ([docker_clean_clone_3582c85.txt](docs/evidence/docker_clean_clone_3582c85.txt)): the
  demo seed ingested 101 articles from 4 feeds and processed them in about 52 s in total,
  giving 2 topics. Two spot-check queries, not a measured quality score: "cancer cells
  treatment" returned three MIT Research cancer articles first (similarity 0.465-0.521);
  "OpenAI valuation" returned first an article on another AI company's valuation (0.438).

## Tests and CI

```bash
pip install -r requirements-dev.txt   # requirements.txt + pytest, pytest-cov, ruff
ruff check .
pytest -rs
```

PostgreSQL cases run only when `TEST_POSTGRES_ADMIN_URL` points to a **throwaway** PostgreSQL
server (each test creates and drops its own database); otherwise they are skipped.

Latest local run ([test_results_4275dad.txt](docs/evidence/test_results_4275dad.txt)),
2026-11-11, commit `4275dad`, Windows, Python 3.14.7, no PostgreSQL test server:
`ruff check .` clean; **1120 passed, 224 skipped, 0 failed**. All 224 skips have the same
reason: `TEST_POSTGRES_ADMIN_URL is not set (no PostgreSQL test server)`.

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) is defined to run on every push
and pull request: Ubuntu, Python 3.12, `pip install -r requirements-dev.txt`,
`ruff check .`, then `pytest -v -rs -o addopts=""` with `TEST_POSTGRES_ADMIN_URL` pointing
at a PostgreSQL 17 service container, so the PostgreSQL cases run there instead of being
skipped. The badge at the top shows the result of the latest run.

## Known limitations

Running and deployment:

- **One worker process only** (do not start uvicorn with `--workers`): the search, login and
  registration rate limits are kept in memory per process, and AI jobs run inside the API
  process. A restart loses a running AI job; at startup, jobs left pending or running are
  marked failed ("Interrupted by application restart"), so a new `POST /ai/process` can
  start at once instead of waiting out the 1-hour job timeout.
- The container runs as root (the Dockerfile sets no other user).
- Rate limits count by the address of the connecting socket. Behind Docker port forwarding
  or a proxy, many clients can appear with the same address and then share one limit.
  Failed logins are counted per username and address, so repeated wrong passwords for a
  username from that shared address can block that user's logins for the window.
- `POST /ingestion/run` ("Rescan sources") runs inside the request until every feed is
  read, and two runs at the same time are not locked against each other.
- Deleting a source loads all its articles into memory before deleting them, so it is slow
  for a large source.
- No automatic backups.
- `/docs` (Swagger UI) is public and needs Internet (loaded from a CDN); the main UI does not.

Accounts and sessions:

- Registering a username that exists answers 409, so anyone can find out which usernames exist.
- With `SESSION_COOKIE_SECURE=false` (the default, for plain HTTP) the session cookie is also
  sent over unencrypted HTTP.
- A session lasts 12 hours from login whatever the activity (no idle timeout); expired
  sessions are removed from the database only when someone logs in.
- The login and registration endpoints do not check the `Origin` header (the other
  cookie-based write endpoints do).
- Passwords are not Unicode-normalised: the same accented password typed with a different
  keyboard input method may not match.
- Raising `PASSWORD_SCRYPT_N` applies to new passwords only; existing hashes are not
  upgraded at login.
- Changing a password saves the new hash and ends the other sessions in two separate
  database commits.
- `X-Admin-Token` requests are not logged or rate limited, and the token's length is not
  checked.
- Error codes differ: a wrong current password is 400, a password that breaks the rules
  is 422, a wrong login is 401; 403 is used both for a missing role and for a failed
  `X-Requested-With`/`Origin` check, and the admin page treats both as "signed out".
- The account bar reads the sign-in state once, when the page loads: after a session
  expires it still shows the username until the next page load. The 429 message shows the
  wait in raw seconds ("Please wait 873 seconds").
- No password recovery by email: a forgotten password can only be reset by an operator with
  `scripts/create_admin.py --reset-password` (keeps the account's role, ends its sessions).
- No account management through the API (listing, disabling or changing the role of
  accounts); only `scripts/create_admin.py` creates or promotes admins.
- SQLite (host runs) does not enforce foreign keys.

Topics, trending and search:

- Topic labels mix heuristic names and BERTopic keywords.
- Topics partly follow the source (some feeds fall mostly into one topic).
- The topic configuration was chosen on the same corpus it is reported on.
- With few articles, topics are broad: the four demo feeds (101 articles) gave 2 topics.
- **Trending has data only when there are articles from the last 24 hours.** Otherwise the
  UI falls back to the last 7 days and says so. Run
  `docker compose exec api python scripts/seed_demo.py --refresh` just before a presentation.
- Public search shows at most 5 results (`ASK_MAX_SOURCES`, default 5).
- **Results are not ordered by the similarity score shown.** The order fuses two rankings
  with reciprocal rank fusion (`app/services/hybrid_search.py`): one by similarity plus a
  freshness bonus of up to 0.05 that fades over about a week, one by query words found
  (rarer words weigh more, a word in the title counts three times, only the first 1500
  characters of the text are read). Near-duplicate stories are shown once. The score
  shown is the plain similarity, so an article with a lower score can rank higher (seen in
  the Docker run: 0.327 above 0.370).
- Search does no stemming ("centers" does not match "center").
- With a two-word query, one matching word is enough, so unrelated articles can appear.
- Articles found only by keyword can show a low similarity score.

Other:

- The PNG logo looks blurry on 2x screens.
- The UI was checked with automated tests in headless Microsoft Edge and manually in Brave;
  Firefox and Safari were not tested.
- Library versions are not pinned (ranges in `requirements*.txt`), and CI runs Python 3.12
  while the dev machine runs 3.14.7, so a test that passes on the dev machine may not pass in CI.
- "Rescan sources" with a real public RSS feed has not been tested from the browser (only
  through the API).
- Model loading takes time at startup: about 30 seconds for a host run on the dev machine,
  about 14 seconds in the Docker run of 2026-11-11.
- Two RSS sources (VentureBeat, AI News) block bots.
- The corpus is a one-day snapshot; ingesting again will not reproduce it. Its articles
  are older than the 24-hour trending window. The UI then asks for the last 7 days (the
  widest window the API accepts) and says so; when that is empty too (as on the snapshot
  today), the trending chips are hidden and the sidebar and Topics chart say no topic is trending.
- PostgreSQL is checked only by CI, the backup/restore run of 2026-10-27 and the Docker
  runs of 2026-11-08 and 2026-11-11; local test runs skip the PostgreSQL cases.

## Reading the code

1. `app/main.py`: app, static UI, middleware.
2. `app/api/routes/`: HTTP endpoints.
3. `app/services/ingestion.py`: feeds to articles.
4. `app/services/analyzer.py`: keyword analysis and extractive summaries.
5. `app/services/topic_model.py`: embeddings + BERTopic batch.
6. `app/services/news_search.py` and `app/services/hybrid_search.py`: search.
