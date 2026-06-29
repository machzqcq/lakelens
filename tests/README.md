# Tests

Three test layers, runnable independently or as a single pipeline.

| Layer | What it tests | Tool | Runtime |
|---|---|---|---|
| **Unit** (backend) | Pure-logic modules: auth utils, RBAC filter resolution (incl. the system-role-neutrality regression + int→str coercion), chatbot SQL safety, **Database Explorer SQL guard**, node-spec lookups, storage abstraction (local mode) | `pytest` | < 5 s |
| **Unit** (frontend) | AuthContext, API client (auth header / 401), ThemeContext | `vitest` + `jsdom` + `@testing-library/react` | < 10 s |
| **Integration** (backend) | FastAPI routes against a real Postgres test DB. Full auth flow, admin RBAC gating, **admin create-user**, **Database Explorer (catalog + read-only query guard + row cap)**, and end-to-end data-scope narrowing across billing **and** analytics (with the `user` role retained — the exact bug scenario). | `pytest` + httpx `AsyncClient` + isolated DB | ~30 s |
| **E2E** | Browser drives the full stack (frontend → backend → DB). Login, navigation, page renders, RBAC visibility, theme switcher. | `Playwright` | 1–3 min |

## Layout

```
tests/
├── docker-compose.test.yml      isolated Postgres + backend + frontend (ports 55432 / 58000 / 53000)
├── run.sh                       one-shot: bring infra up, run all layers, tear down
├── backend/
│   ├── pytest.ini
│   ├── conftest.py              shared fixtures: test DB, client, authed_client
│   ├── unit/                    no DB, no network
│   └── integration/             real Postgres via docker-compose.test.yml
├── frontend/
│   ├── package.json             vitest deps
│   ├── vitest.config.ts
│   ├── setup.ts                 jsdom + mocks
│   └── src/                     mirrors frontend/src layout
└── e2e/
    ├── package.json             playwright
    ├── playwright.config.ts
    └── tests/                   *.spec.ts
```

## Prerequisites

- Docker + Docker Compose
- Python 3.12 (matching `backend/pyproject.toml`)
- Node 20+
- Optional: `uv` for fast Python deps; otherwise `pip` works

## Quick start

```bash
# From the repo root
cd databricks_cost_app

# Bring up the isolated test infra (Postgres on 55432, backend on 58000,
# frontend on 53000 — all separate from your dev stack)
docker compose -f tests/docker-compose.test.yml up -d --build

# Wait for the backend to be healthy (takes ~10s after build)
until curl -sf http://localhost:58000/health > /dev/null; do sleep 1; done

# ----- backend tests -----
cd tests/backend
pip install -e ../../backend
pip install pytest pytest-asyncio httpx
pytest unit/                                      # ~3s
pytest integration/                               # ~30s

# ----- frontend tests -----
cd ../../tests/frontend
npm install
npm run test                                      # vitest watch mode → press q to quit
npm run test:run                                  # single run

# ----- e2e tests -----
cd ../../tests/e2e
npm install
npx playwright install --with-deps chromium
npx playwright test                               # headless, all browsers
npx playwright test --ui                          # interactive UI mode
npx playwright show-report                        # last run's HTML report

# Teardown
cd ../..
docker compose -f tests/docker-compose.test.yml down -v
```

Or run everything with one command:

```bash
./tests/run.sh
```

## CI-friendly run (no host installs)

The repo's `tests/Dockerfile.runner` (see below) packages pytest + playwright
into a single image so CI doesn't need anything beyond Docker.

```bash
docker compose -f tests/docker-compose.test.yml up -d --build
docker run --rm --network host \
    -v "$(pwd)":/workspace -w /workspace \
    pricing-app-test-runner ./tests/run.sh --no-up --no-down
docker compose -f tests/docker-compose.test.yml down -v
```

## Environment

The test stack is fully self-contained:

- **Test DB**: Postgres 16 on port `55432`, db `dbx_cost_test`, user
  `test_user` / `test_pass`. Backed by `tmpfs` so every `down -v` is
  pristine.
- **Bootstrap admin**: `admin@test.local` / `TestAdmin12345!`. Created on
  backend startup (we set `DEFAULT_ADMIN_EMAIL`/`PASSWORD`).
- **Data**: parquet files from `data/` mounted **read-only**. Tests
  cannot accidentally mutate dev data.
- **OAuth providers**: none configured — the buttons render disabled
  (we test that behavior).
- **LLM**: no API keys. Chatbot-end-to-end tests are marked with the
  `@requires_llm` marker and skipped unless `LLM_TEST_KEY` is set.

## What's intentionally NOT tested

| Skipped | Why |
|---|---|
| Live Databricks extraction | Requires a real workspace + PAT |
| AWS SES delivery | Verifying email link is in stdout, not testing SES itself |
| OAuth full round-trip | Mocking provider userinfo is brittle; the OAuth code is small and covered manually |
| Chatbot LLM round-trip (default) | Costs $; opt-in via `LLM_TEST_KEY` env var |
| Cloud deploy scripts | Out of scope — covered manually before each cloud cutover |

## Adding a new test

- **Backend unit**: drop a `test_<thing>.py` in `tests/backend/unit/`. Pure
  imports from `backend/<module>`. No fixtures.
- **Backend integration**: drop in `tests/backend/integration/`. Use the
  `client` (anonymous) or `admin_client` / `user_client` fixtures from
  `conftest.py`.
- **Frontend unit**: drop a `*.test.ts(x)` next to the component in
  `tests/frontend/src/`. Import from `frontend/src/...` (configured
  alias in `vitest.config.ts`).
- **E2E**: drop a `*.spec.ts` in `tests/e2e/tests/`. The `authed`
  fixture in `fixtures.ts` logs you in as the bootstrap admin.
