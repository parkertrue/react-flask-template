# React + Flask Template

A ready-to-use starting point for a React + Flask + MySQL web app, with auth, tests, CI and a hardened production setup already wired.

* **Frontend**: React (Vite), in TypeScript
* **Backend**: Flask + SQLAlchemy + Alembic, MySQL, Redis (sessions, rate limits and a job queue), and a worker for slow jobs such as sending email
* **Production**: Docker Compose behind an HTTPS Nginx reverse proxy, with MySQL and Redis bundled or external (RDS, ElastiCache), or on a container platform such as Amazon ECS
* **Auth**: sign-up and password reset through an emailed link, JWT access tokens plus rotating, revocable refresh tokens in HttpOnly cookies
* **Account**: change the email (confirmed by a link, with an undo link to the old address) or the password, see every signed-in device and log any of them out, download your data, delete the account
* **Tests**: unit, integration and end-to-end, run in GitHub Actions
* **Legal**: placeholder privacy notice, terms, contact page and `security.txt`

It ships with auth and a small **notes** feature (list, create, edit, delete) that shows one feature wired end to end, meant to be replaced by your real app: see [Starting a New App](#starting-a-new-app-from-this-template).

More detail lives in [docs/deployment.md](docs/deployment.md) (running in production), [docs/personal-data.md](docs/personal-data.md) (what the app stores and the legal pages) and [CLAUDE.md](CLAUDE.md) (how the code is built).

---

## Required Software

* [Docker & Docker Compose](https://www.docker.com/products/docker-desktop/)
* [Python 3.15](https://www.python.org/downloads/)
* [Node.js 26 LTS](https://nodejs.org/)
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

MySQL, Redis and Mailpit (which catches the email the app sends) run in Docker; Flask, the worker and React run on your machine, with hot reloading.

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

If you work with Claude Code, also create `temp/HANDOFF.md` (`temp/` is gitignored) for what is yours alone and would mean nothing to anyone else: how your machine differs (OS, shell quirks, tool versions), your servers and how to reach them, the current state (branch, last merge, test counts on `main`), and how you like to work. Issues never go there: every open issue is in `.claude/skills/_audit-shared/OPEN-ISSUES.md`. A start:

```markdown
# Handoff

Read this, then `.claude/skills/_audit-shared/OPEN-ISSUES.md`, before
starting.

## State
## How I work
## This machine
## Servers
```

A new chat then starts with *"Read temp/HANDOFF.md and let's continue."* Bring its State up to date before ending a session.

### Every Day

Run each in its own terminal:

```bash
docker compose --env-file .env.dev -f docker-compose.dev.yml up   # MySQL :3306, Redis :6379, Mailpit :8025
cd backend && ./run_dev.sh                                        # Migrates, then starts Flask and the worker
cd frontend && npm run dev                                        # Vite dev server
```

| Service  | URL |
|----------|-----|
| Frontend | [http://localhost:5173](http://localhost:5173) |
| Backend  | [http://localhost:5000/api/health](http://localhost:5000/api/health) |
| Email    | [http://localhost:8025](http://localhost:8025) (Mailpit: every email the worker sent) |

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
python export_schemas.py     # After changing a schema (then npm run api-types)
ruff check .                 # Lint
mypy                         # Type check (strict)

# From frontend/
npm run lint
npm run typecheck            # Type check (strict)
npm run api-types            # The API's types, from the backend's schemas
npm run test:run             # Unit tests once (npm run test for watch mode)
npm run test:coverage        # What CI runs
npx playwright install chromium   # E2E: first time, and after each Playwright update
npm run test:e2e             # E2E against the full Docker stack at https://localhost:8443
```

E2E needs a [certificate](#https-certificate). Locally, Playwright reuses an E2E stack that is already running, even after the code changed; after changing app code, take it down first from the repository root: `docker compose --env-file .env.test -f docker-compose.test.yml --profile e2e down -v`.

### Continuous Integration

GitHub Actions runs lint, every test suite and config checks on each push and pull request to `main`, and the integration, E2E and smoke jobs nightly too. Dependabot opens weekly update PRs; for security fixes as soon as an advisory is published, enable Dependabot alerts and security updates under Settings > Advanced Security, and turn off "Dismiss low impact alerts" under Dependabot rules.

To stop a failing check from merging, require these status checks on `main` (Settings > Branches): Backend unit, Frontend unit, Scaffold, Compose files, Workflows, Dockerfiles, Nginx config, Backend integration, Platform smoke, Deploy smoke and Playwright E2E.
Leave "Require branches to be up to date before merging" off: with it on, each merge sends every other open PR back for a rebase and a full CI run, while CI on `main` after each merge already catches what two PRs break together.

---

## Production

Everything runs in Docker; only Nginx is published (ports 80 and 443). [docs/deployment.md](docs/deployment.md) covers the details: database users, changing secrets later, Let's Encrypt, external MySQL or Redis, container platforms such as ECS, logs, backups and restoring.

**Not included:** alerts, log shipping, scheduled off-host backups, point-in-time recovery, disk encryption and host hardening are left to the tools made for them, and certificate renewal is not provided yet; [Operating in Production](docs/deployment.md#operating-in-production) says which to reach for. Set them up before the server holds real data.

### Environment File

Create `.env.prod` and fill in every value. Production refuses placeholder passwords and a `SECRET_KEY` under 32 characters. Email goes out through a mail provider you sign up with: see [Sending Email](docs/deployment.md#sending-email).

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

Locally too, sign-up needs a real mail provider: production refuses Mailpit and the example's email values, and its worker stops without them ([Sending Email](docs/deployment.md#sending-email)). To try the app without one, use the dev or E2E stack, which deliver to Mailpit.

### Build and Start

```bash
docker compose --env-file .env.prod build --pull --provenance=false
docker compose --env-file .env.prod up
```

The app is at `https://<SERVER_NAME>`. On a server, deploy with `deploy.sh` instead, which builds one commit of `main`, migrates first, and rolls back by itself when a deploy fails: see [Redeploying](docs/deployment.md#redeploying).

**Stop:** `docker compose --env-file .env.prod down`. **Full reset** (⚠️ deletes the database): add `--volumes --remove-orphans`.

---

## Starting a New App From This Template

**What is example code.** Notes, a small CRUD feature that shows how a feature is wired end to end, and the API-status demo on the home page. Everything else is what every app keeps: auth, the account page and `/api/account`, `/api/health` (the Docker healthchecks and Playwright wait on it), the layout, forms and dialogs.

**Where a feature plugs in:**
- `backend/app/features.py`: its blueprint
- `frontend/src/routes.tsx`: its page's route, and `frontend/src/__tests__/routes.test.tsx`
- `frontend/src/components/layout/Navbar.tsx` and `frontend/src/pages/HomePage.tsx`: the links to it, and their tests
- `AFTER_LOGIN_PATH` in `frontend/src/auth/GuestRoute.tsx`: where logging in leads

A feature's background jobs plug in through its own blueprint, as its data export does: `@job(<blueprint>)` on the function (`backend/app/utils/jobs.py`; sign-up's is in `backend/app/auth/routes.py`), queued from a route with `.send(...)`. Queue a job before committing when the job is the request's point; such a job must not read a row the request writes, which the worker cannot see until the commit (pass it the values it needs, or queue after the commit); when the write must stand on its own, queue after committing and catch and log `JobQueueUnavailable`, as the password reset does, or a Redis outage answers 503 with the row already saved and the user's retry saves it again. Its unit tests read what a request queued with the `jobs` fixture, run it with `run_jobs`, read the email a job sent with `outbox`, and take the queue down with `queue_down` (`backend/tests/unit/conftest.py`).

CI's Scaffold job deletes the examples and edits exactly these files (`.github/scripts/remove_examples.py`), renames the app (step 5), then runs lint and the unit suites, so shared code can't come to depend on an example or the template's name. Changing a wiring point means changing the script with it.

**Your own repository:** create an empty repository for the app on GitHub (no README, license or `.gitignore`, which would conflict with the first push), then clone the template, keeping its history, and push it there:

```bash
git clone https://github.com/parkertrue/react-flask-template.git <your-app>
cd <your-app>
git remote rename origin template
git remote add origin <your new repository's URL>
git push -u origin main
```

The template stays a remote, so its later fixes merge in like any branch ([Taking Template Fixes](#taking-template-fixes)). GitHub's "Use this template" button makes a copy with no shared history, which can only take them by hand: use it only for a copy you will never update. Then set up the repository as [Continuous Integration](#continuous-integration) says: Dependabot alerts and security updates, and the required status checks.

**Before you start:** decide what the app does, who uses it and its first feature, and add an issue to `.claude/skills/_audit-shared/OPEN-ISSUES.md` for each piece of work that comes out of it. The steps below replace notes with that first feature.

**Steps:**

1. Rename the Compose projects (`name:` at the top of each compose file: `app_dev`, `app_test`, `app`) and the databases in `.env.dev` and `.env.test` (`appdb_dev`, `appdb_test`). Two apps built from this template then never share containers or volumes, and your dev and test stacks start with empty databases.
2. Replace notes with your first feature, in one of two ways:
   - **Rename it** into your feature, the quickest start when that feature is also short text items a user adds, edits and deletes: `backend/app/notes/`, `frontend/src/features/notes/` and their tests (`backend/tests/unit/notes/`, `backend/tests/integration/notes/`, `frontend/e2e/notes-crud.spec.ts`).
   - **Delete it**, and build your feature in the same shape: delete those folders and files. [CLAUDE.md](CLAUDE.md)'s "Building a Feature" lists every rule notes follows, written to hold without it.

   Either way, register each table that holds a user's rows for the data download, as `backend/app/notes/routes.py` does (`register_export`); `tests/unit/test_exports.py` fails on one left out.

   Either way, delete `backend/migrations/versions/0002_notes.py` (step 4 generates yours) and update the wiring points above, and regenerate the API's types: `python export_schemas.py` from `backend/`, then `npm run api-types` from `frontend/` (again whenever a schema changes). Then delete `.github/scripts/remove_examples.py` and the Scaffold job in `.github/workflows/ci.yml`, and remove `Scaffold` from the list of required status checks under [CI](#continuous-integration) (the Workflows job fails while that list names a job that doesn't exist) and from Settings > Branches: they only prove that the template's examples can be removed, and the import rules keep shared code off your features.
3. Remove the API-status demo, unless you want it: delete `frontend/src/features/health/` and `frontend/e2e/api-status.spec.ts`, the `ApiStatus` import and element in `frontend/src/pages/HomePage.tsx`, and the `vi.mock` of `ApiStatus` in `frontend/src/pages/__tests__/HomePage.test.tsx`, with `vi` in its import.
4. Generate a migration for your tables. From `backend/`, with `.env.dev` loaded as in [Database Schema Changes](#database-schema-changes). If the dev backend ran after step 1 while `0002_notes.py` still existed, the database refers to a migration that is gone: reset it first (`docker compose --env-file .env.dev -f docker-compose.dev.yml down -v`, then start it again).

   ```bash
   flask db upgrade
   flask db migrate -m "<your feature>" --rev-id 0002_<your_feature>
   ```

   Upgrade first: Alembic only writes a migration against an up-to-date database. In the generated file, keep only the `op.drop_table(...)` lines in `downgrade()`: MySQL will not drop an index that a foreign key uses, and dropping the table drops its indexes anyway. Then run `./run_tests.sh integration`, whose `test_migrations.py` checks that the migrations match the models and undo cleanly.
5. Name the app, without using anyone else's trademark, in three places: `APP_NAME` in `frontend/src/appInfo.ts`, the `<title>` in `frontend/index.html`, and `APP_NAME` in `backend/app/config.py`, which the backend introduces itself by (a test checks that the three match, and that no other code or test writes the name). Describe it in `APP_TAGLINE` beside the name. Put the name in the sender of the emails the app sends: `EMAIL_FROM` in `.env.dev` and `.env.test`, and in your `.env.prod`. Replace the placeholder icon, `frontend/public/favicon.svg`.
6. Rewrite this README, `docs/` and `CLAUDE.md` for your app, keeping CLAUDE.md's "Building a Feature" for your next features with its examples pointing at your own, and choose its license: replace `LICENSE` and the `license` field in `frontend/package.json`, then run `npm install` in `frontend/` so `package-lock.json` matches (the template is MIT-0, so your app owes it no notice). Delete `.claude/skills/audit-scaffold/`, which acts out these steps on the template, and remove it from `/audit`'s `periodic` tier and Docker order (`.claude/skills/audit/SKILL.md`); keep the other audits in `.claude/skills/` and update their references to notes, to `audit-scaffold` and to the Scaffold job, or delete them. Keep `.claude/skills/_audit-shared/OPEN-ISSUES.md` as your app's list of open work, starting with its production to-dos, and `DECISIONS.md` beside it as its accepted trade-offs.
7. Write the legal pages and work through the "Before launch" list in [docs/personal-data.md](docs/personal-data.md).

### Taking Template Fixes

The template keeps changing after you copy it, security fixes included. Check what is new about once a month, and merge soon any commit whose message starts with `fix:`:

```bash
git fetch template
git log --oneline main..template/main   # what changed since your last merge
git switch -c template-update
git merge template/main
```

Git finds the last template commit you have by itself. Conflicts come only where your app changed what the template changed too:

- **A file you deleted** (the notes example, the API-status demo, `remove_examples.py`, `audit-scaffold`): `git rm` it.
- **A file you rewrote** (this README, `docs/`, `CLAUDE.md`, the audit skills): read what the template changed, `git log -p HEAD..template/main -- <file>`, and carry over what applies to your app.
- **The lock files** (`backend/requirements*.txt`, `frontend/package-lock.json`): keep yours (`git checkout --ours <file>`), then regenerate them, with `backend/lock_deps.sh` or `npm install` in `frontend/`, since they are never edited by hand.
- **A migration from the template:** its `down_revision` may name one your app deleted (`0002_notes`). Give it your next `--rev-id` number, in its file name and `revision`, set its `down_revision` to your newest migration, then run `./run_tests.sh integration`.

Then regenerate the API's types (`python export_schemas.py` from `backend/`, `npm run api-types` from `frontend/`), run lint and both unit suites, and open a pull request, so CI runs everything before the merge reaches `main`.

## License

MIT-0 (MIT No Attribution), see [`LICENSE`](LICENSE): reuse the template without keeping any notice. The production build also writes the bundled libraries' own notices to `third-party-licenses.txt`, which nginx serves beside the app.
