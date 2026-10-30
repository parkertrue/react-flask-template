# React + Flask Template

A ready-to-use starting point for a React + Flask + MySQL web app, with auth, tests, CI and a hardened production setup already wired.

* **Frontend**: React (Vite)
* **Backend**: Flask + SQLAlchemy + Alembic, MySQL, Redis (sessions and rate limits)
* **Production**: Docker Compose behind an HTTPS Nginx reverse proxy, with MySQL and Redis bundled or external (RDS, ElastiCache), or on a container platform such as Amazon ECS
* **Auth**: JWT access tokens plus rotating, revocable refresh tokens in HttpOnly cookies
* **Tests**: unit, integration and end-to-end, run in GitHub Actions
* **Legal**: placeholder privacy notice, terms, contact page and `security.txt`

It ships with auth and a small **notes** feature (list, create, edit, delete) that shows one feature wired end to end, meant to be replaced by your real app: see [Starting a New App](#starting-a-new-app-from-this-template).

More detail lives in [docs/deployment.md](docs/deployment.md) (running in production), [docs/personal-data.md](docs/personal-data.md) (what the app stores and the legal pages) and [CLAUDE.md](CLAUDE.md) (how the code is built).

---

## Required Software

* [Docker & Docker Compose](https://www.docker.com/products/docker-desktop/)
* [Python 3.14](https://www.python.org/downloads/)
* [Node.js 24 LTS](https://nodejs.org/)
* [Git Bash](https://git-scm.com/download/win) (Windows only): use it for every command in this README

Make sure Docker is running before any `docker compose` command.

## Environment Files

| File | In git | Used by |
|------|--------|---------|
| `.env.dev` | Yes, throwaway values | Development |
| `.env.test` | Yes, throwaway values | Integration and E2E tests |
| `.env.prod` | No, copy from `.env.prod.example` | Production |

Dev and test work as cloned. Only production needs a file of its own (see [Production](#production)).

---

## Development

MySQL and Redis run in Docker; Flask and React run on your machine, with hot reloading.

### One-Time Setup

```bash
docker compose --env-file .env.dev -f docker-compose.dev.yml pull

cd backend
python -m venv .venv
source .venv/Scripts/activate   # Windows (Git Bash); Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt

cd ../frontend
npm install
```

### Every Day

Run each in its own terminal:

```bash
docker compose --env-file .env.dev -f docker-compose.dev.yml up   # MySQL :3306, Redis :6379
cd backend && ./run_dev.sh                                        # Migrates, then starts Flask
cd frontend && npm run dev                                        # Vite dev server
```

| Service  | URL |
|----------|-----|
| Frontend | [http://localhost:5173](http://localhost:5173) |
| Backend  | [http://localhost:5000/api/health](http://localhost:5000/api/health) |

Stop with `CTRL+C` in each terminal, then `docker compose --env-file .env.dev -f docker-compose.dev.yml down`.

### Database Schema Changes

`run_dev.sh` applies pending migrations each time it starts. After changing the models, from `backend/` with the virtualenv active and the dev database running:

```bash
set -a && source ../.env.dev && set +a
flask db migrate -m "describe change" --rev-id 0003_describe_change
flask db upgrade
```

Give each migration a `--rev-id` of the next number and a short name, as `0001_users` and `0002_notes` do.

### Python Dependencies

Edit `backend/requirements.in` (the app) or `requirements-dev.in` (test tools), never the `.txt` locks. Then, from `backend/` (needs Docker):

```bash
./lock_deps.sh             # Re-resolve after editing a .in file
./lock_deps.sh --upgrade   # Move every package to its newest release
pip install -r requirements-dev.txt
```

---

## Testing

```bash
# From backend/
./run_tests.sh unit          # Fast: in-memory SQLite, no Docker
./run_tests.sh integration   # Real MySQL + Redis in Docker
./run_tests.sh combined      # Both, with one coverage report
ruff check .                 # Lint

# From frontend/
npm run lint
npm run test:run             # Unit tests once (npm run test for watch mode)
npm run test:coverage        # What CI runs
npx playwright install chromium   # E2E, first time only
npm run test:e2e             # E2E against the full Docker stack at https://localhost:8443
```

E2E needs a [certificate](#https-certificate). Locally, Playwright reuses an E2E stack that is already running, even after the code changed; after changing app code, take it down first from the repository root: `docker compose --env-file .env.test -f docker-compose.test.yml --profile e2e down -v`.

### Continuous Integration

GitHub Actions runs lint, every test suite and config checks on each push and pull request to `main`, and the integration and E2E suites nightly too. Dependabot opens weekly update PRs; for security fixes as soon as an advisory is published, enable Dependabot alerts and security updates under Settings > Advanced Security, and turn off "Dismiss low impact alerts" under Dependabot rules.

To stop a failing check from merging, require these status checks on `main` (Settings > Branches): Backend unit, Frontend unit, Scaffold, Compose files, Workflows, Dockerfiles, Nginx config, Backend integration, Platform smoke and Playwright E2E.

---

## Production

Everything runs in Docker; only Nginx is published (ports 80 and 443). [docs/deployment.md](docs/deployment.md) covers the details: database users, changing secrets later, Let's Encrypt, external MySQL or Redis, container platforms such as ECS, and logs.

### Environment File

Create `.env.prod` and fill in every value. Production refuses placeholder passwords and a `SECRET_KEY` under 32 characters.

```bash
cp .env.prod.example .env.prod
openssl rand -hex 32   # Generates a value
```

### HTTPS Certificate

Nginx needs `fullchain.pem` and `privkey.pem` in `nginx/certs/` (E2E tests too). A self-signed one for local testing (set `SERVER_NAME=localhost` in `.env.prod`); for a real domain, see [Let's Encrypt](docs/deployment.md#real-domain-lets-encrypt):

```bash
mkdir -p nginx/certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/certs/privkey.pem \
  -out nginx/certs/fullchain.pem \
  -subj "/C=US/ST=California/L=San Francisco/O=Dev/CN=localhost"
```

### Build and Start

```bash
docker compose --env-file .env.prod build --provenance=false
docker compose --env-file .env.prod up
```

The app is at `https://<SERVER_NAME>`. To deploy a change to a running app without downtime if a migration fails, see [Redeploying](docs/deployment.md#redeploying).

**Stop:** `docker compose --env-file .env.prod down`. **Full reset** (⚠️ deletes the database): add `--volumes --remove-orphans`.

---

## Starting a New App From This Template

**What is example code.** Notes, a small CRUD feature that shows how a feature is wired end to end, and the API-status demo on the home page. Everything else is what every app keeps: auth, the account page and `/api/account`, `/api/health` (the Docker healthchecks and Playwright wait on it), the layout, forms and dialogs.

**Where a feature plugs in:**
- `backend/app/features.py`: its blueprint
- `frontend/src/routes.jsx`: its page's route, and `frontend/src/__tests__/routes.test.jsx`
- `frontend/src/components/layout/Navbar.jsx` and `frontend/src/pages/HomePage.jsx`: the links to it, and their tests
- `AFTER_LOGIN_PATH` in `frontend/src/auth/GuestRoute.jsx`: where logging in leads

CI's Scaffold job deletes the examples and edits exactly these files (`.github/scripts/remove_examples.py`), then runs lint and the unit suites, so shared code can't come to depend on an example. Changing a wiring point means changing the script with it.

**Steps:**

1. Rename the Compose projects (`name:` at the top of each compose file: `app_dev`, `app_test`, `app`) and the databases in `.env.dev` and `.env.test` (`appdb_dev`, `appdb_test`). Two apps built from this template then never share containers or volumes, and your dev and test stacks start with empty databases.
2. Replace notes with your first feature, in one of two ways:
   - **Rename it** into your feature, the quickest start when that feature is also a list of things a user owns: `backend/app/notes/`, `frontend/src/features/notes/` and their tests (`backend/tests/unit/notes/`, `backend/tests/integration/notes/`, `frontend/e2e/notes-crud.spec.js`).
   - **Delete it**, and build your feature in the same shape: delete those folders and files.

   Either way, delete `backend/migrations/versions/0002_notes.py` (step 4 generates yours) and update the wiring points above. Then delete `.github/scripts/remove_examples.py` and the Scaffold job in `.github/workflows/ci.yml`, and remove `Scaffold` from the list of required status checks under [CI](#continuous-integration) (the Workflows job fails while that list names a job that doesn't exist) and from Settings > Branches: they only prove that the template's examples can be removed, and the import rules keep shared code off your features.
3. Remove the API-status demo, unless you want it: delete `frontend/src/features/health/` and `frontend/e2e/api-status.spec.js`, the `ApiStatus` import and element in `frontend/src/pages/HomePage.jsx`, and the `vi.mock` of `ApiStatus` in `frontend/src/pages/__tests__/HomePage.test.jsx`, with `vi` in its import.
4. Generate a migration for your tables. From `backend/`, with `.env.dev` loaded as in [Database Schema Changes](#database-schema-changes). If the dev backend ran after step 1 while `0002_notes.py` still existed, the database refers to a migration that is gone: reset it first (`docker compose --env-file .env.dev -f docker-compose.dev.yml down -v`, then start it again).

   ```bash
   flask db upgrade
   flask db migrate -m "<your feature>" --rev-id 0002_<your_feature>
   ```

   Upgrade first: Alembic only writes a migration against an up-to-date database. In the generated file, keep only the `op.drop_table(...)` lines in `downgrade()`: MySQL will not drop an index that a foreign key uses, and dropping the table drops its indexes anyway. Then run `./run_tests.sh integration`, whose `test_migrations.py` checks that the migrations match the models and undo cleanly.
5. Name the app, without using anyone else's trademark: `APP_NAME` in `frontend/src/appName.js` and the `<title>` in `frontend/index.html` (a test checks they match), and describe it in `APP_TAGLINE` beside the name. Replace the placeholder icon, `frontend/public/favicon.svg`.
6. Rewrite this README, `docs/` and `CLAUDE.md` for your app, and choose its license: replace `LICENSE` and the `license` field in `frontend/package.json`, then run `npm install` in `frontend/` so `package-lock.json` matches (the template is MIT-0, so your app owes it no notice). Delete `.claude/skills/audit-scaffold/`, which acts out these steps on the template, and remove it from `/audit`'s `periodic` tier and Docker order (`.claude/skills/audit/SKILL.md`); keep the other audits in `.claude/skills/` and update their references to notes and to `audit-scaffold`, or delete them.
7. Write the legal pages and work through the "Before launch" list in [docs/personal-data.md](docs/personal-data.md).

## License

MIT-0 (MIT No Attribution), see [`LICENSE`](LICENSE): reuse the template without keeping any notice. The production build also writes the bundled libraries' own notices to `third-party-licenses.txt`, which nginx serves beside the app.
