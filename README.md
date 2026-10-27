# React + Flask Template

This repository is a ready-to-use template for a React + Flask + MySQL web application, designed to eliminate the overhead of initial project scaffolding and environment configuration. 

**Features**: 

* Fully Dockerized production setup behind an HTTPS Nginx reverse proxy, with MySQL and Redis bundled or external (managed services such as Amazon RDS and ElastiCache), or on a container platform such as Amazon ECS ([Deploying to a Platform](#deploying-to-a-platform))
* Hybrid development setup (local app + Dockerized database)
* Flask application using the factory pattern
* MySQL database with Alembic migrations
* JWT auth: short-lived access tokens plus rotating, revocable refresh tokens in HttpOnly cookies; a session ends after 7 days unused, and 30 days after login at most
* Redis for refresh-token tracking and rate limiting
* Placeholder privacy notice, terms (accepted at registration, with the version recorded), contact page and `security.txt`, to write for your app ([Personal Data and Legal Pages](#personal-data-and-legal-pages))
* Unit, integration, and end-to-end tests, run in GitHub Actions

**Full-stack template**:

* **Frontend**: React (Vite)
* **Backend**: Flask + SQLAlchemy + Alembic
* **Database**: MySQL
* **Sessions/Rate limits**: Redis
* **Reverse proxy (prod)**: Nginx
* **Containers**: Docker / Docker Compose

The app ships with auth and a minimal **notes** feature: list, create, edit and delete. Notes is a deliberately thin example of one feature wired end to end (model, schema, route, API service, hook, components, tests), meant to be replaced by your real app. See [Starting a New App](#starting-a-new-app-from-this-template).

---

## Required Software

Make sure the following tools are installed before running the project:

* **Docker & Docker Compose**  
  Used for MySQL, Redis, tests, and production builds.  
  [https://www.docker.com/products/docker-desktop/](https://www.docker.com/products/docker-desktop/)

* **Python 3.14**  
  Used for the Flask backend. The same version the backend image runs and the dependency locks are resolved for.  
  [https://www.python.org/downloads/](https://www.python.org/downloads/)

* **Node.js 24 LTS (includes npm)**  
  Used for the React frontend (Vite).  
  [https://nodejs.org/](https://nodejs.org/)

* **Git Bash (Windows users only)**  
  Provides a Unix-like shell on Windows so you can use the same commands as Linux/macOS.  
  Installed automatically with Git for Windows.  
  [https://git-scm.com/download/win](https://git-scm.com/download/win)

> ⚠️ **Windows users:** Use Git Bash for all commands in this README.  
> ⚠️ **All users:** Make sure Docker is running before executing any docker compose commands.

---

## Environment Files

| File | In git | Used by |
|------|--------|---------|
| `.env.dev` | Yes, throwaway values | Development (local backend + frontend, Docker DB + Redis on 127.0.0.1) |
| `.env.test` | Yes, throwaway values | Integration and E2E tests |
| `.env.prod` | No, create from `.env.prod.example` | Production (fully Dockerized) |

Dev and test work as cloned. Production is the only file to create:

```bash
cp .env.prod.example .env.prod
```

It holds only the nine values that differ per deployment (including `SERVER_NAME`, the domain nginx serves), plus `COMPOSE_PROFILES`, which runs the bundled MySQL and Redis ([External Database or Redis](#external-database-or-redis) replaces either); hosts, ports and `APP_ENV` are fixed in `docker-compose.yml`. Set strong, unique values for every password and `SECRET_KEY`. Production refuses to start with a `SECRET_KEY` shorter than 32 characters or with the example file's placeholder passwords. Generate values with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

nginx reaches the backend at a fixed address, `10.217.0.10`, on a network of its own (`10.217.0.0/24`), so a redeployed backend is reached the moment it starts. If that range is already in use on the server, add `EDGE_SUBNET_PREFIX=10.x.y` (three numbers) to `.env.prod`.

**Database users.** The database has two users. The app's (`DB_USER`) may read and write rows but never change the schema, so a compromised backend cannot drop or alter a table. The migration user (`DB_MIGRATION_USER`) owns the schema, and only the one-off `migrate` service gets its password; the root password reaches only the `db` container. The bundled MySQL creates both when its volume is first created (`db/init/01-app-user.sh`), in every environment; for an external database, you create them ([External Database or Redis](#external-database-or-redis)). In production, the backend refuses to start if the app's user can do more than read and write rows.

**What the app reads.** The backend reads one URL per service: `DATABASE_URL` (the app's user), `REDIS_URL`, and, for `migrate` alone, `MIGRATION_DATABASE_URL`. `docker-compose.yml` builds them from the values above, and `.env.dev` and `.env.test` spell them out. On a container platform, each password may instead come from a variable of its own (`DATABASE_PASSWORD`, `MIGRATION_DATABASE_PASSWORD`, `REDIS_PASSWORD`), which replaces the one in its URL, so a secrets store can supply just the password ([Deploying to a Platform](#deploying-to-a-platform)). `docker-compose.yml` passes none of them to its containers, so with Compose the password stays in the URL. A password written inside a URL must be percent-encoded; the generator above only produces characters that need none.

**Changing a value later.** The database keeps its own copy of its users and passwords; `.env.prod` only tells the app what they are. Editing one in `.env.prod` alone therefore breaks something: a new `DB_PASSWORD` makes the next deploy fail at `migrate` within seconds (it logs in as the app's user to check its grants), and the app is down, answering 502 or 504, until the password is fixed; a new `DB_MIGRATION_PASSWORD` makes the next deploy fail at `migrate` too, and the running app keeps serving only if that deploy changes nothing else (see [Build and Start](#build-and-start) for a deploy that keeps it serving whatever fails). Renaming `DB_USER`, `DB_MIGRATION_USER` or `DB_NAME` on an existing database needs more than this and is not covered here. Change it in the database first, then in `.env.prod`, then run `docker compose --env-file .env.prod up -d`. With the bundled MySQL, which reads the `DB_*` values only when its volume is first created, for `DB_USER` or `DB_MIGRATION_USER`:

```bash
docker compose --env-file .env.prod exec db mysql -uroot -p -e "ALTER USER '<user>'@'%' IDENTIFIED BY '<new password>'"
```

For a new `DB_ROOT_PASSWORD`, change both `'root'@'%'` and `'root'@'localhost'`; nothing outside the `db` container holds it. A new `REDIS_PASSWORD` needs only `up -d`. A new `SECRET_KEY` signs every user out.

---

# Development Mode

The dev database and Redis run in Docker, while Flask and React run locally for faster iteration, hot reloading, and easier debugging.

**Architecture (Dev)**

* MySQL → Docker
* Redis → Docker
* Flask → Local machine
* React → Local machine

---

## One-Time Setup (Dev)

These steps only need to be done **once per machine** (or when dependencies change).

### 1: Pull Docker Images (DB + Redis)

```bash
docker compose --env-file .env.dev -f docker-compose.dev.yml pull
```

### 2: Backend Virtual Environment

From `backend/`:

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows (Git Bash)
source .venv/bin/activate       # Linux/macOS
pip install -r requirements-dev.txt
```

`requirements-dev.txt` adds the test tools on top of `requirements.txt`, which is all the production image installs.

### 3: Frontend Dependencies

From `frontend/`:

```bash
npm install
```

---

## Daily Development Workflow

These are the commands you'll run **every time you start working**.

### Start Database + Redis (Dev)

```bash
docker compose --env-file .env.dev -f docker-compose.dev.yml up
```

MySQL will be available on `localhost:3306`, Redis on `localhost:6379`.

---

### Start Backend (Dev)

From `backend/`:

```bash
./run_dev.sh
```

What this does:
* Loads `.env.dev`
* Activates virtual environment (if not already active)
* Waits for MySQL and Redis to be ready
* Runs `flask db upgrade` as the migration user
* Starts the Flask app as the app's user, which cannot change the schema, as in production

`.env.dev` turns the Flask debugger on. To run without it, override it from the shell: `FLASK_DEBUG=0 ./run_dev.sh`.

---

### Start Frontend (Dev)

From `frontend/`:

```bash
npm run dev
```

The dev server listens on localhost only. To open it from another device on your network, run `npm run dev -- --host`.

**Dev URLs**

| Service  | URL |
|----------|-----|
| Frontend | [http://localhost:5173](http://localhost:5173) |
| Backend  | [http://localhost:5000/api/health](http://localhost:5000/api/health) |

---

## Database Schema Changes (During Dev)

`run_dev.sh` applies pending migrations each time it starts. To generate one after changing the SQLAlchemy models, from `backend/` with the virtualenv active and the dev database running, load the dev environment first (the `flask` command needs it; its `MIGRATION_DATABASE_URL` connects as the user that owns the schema):

```bash
set -a && source ../.env.dev && set +a
flask db migrate -m "describe change" --rev-id 0003_describe_change
flask db upgrade
```

Migration files are named after their revision id alone (`backend/migrations/alembic.ini`), so give each one a `--rev-id` of the next number and a short name, as `0001_users` and `0002_notes` do.

---

## Python Dependencies (During Dev)

`requirements.in` lists the packages the app imports and `requirements-dev.in` the test tools. The `.txt` files are locks compiled from them: every package, transitive ones included, pinned to an exact version, so each install and image build gets exactly what was tested. Never edit the `.txt` files by hand. After changing a `.in` file, from `backend/` (needs Docker):

```bash
./lock_deps.sh             # Re-resolve after editing a .in file
./lock_deps.sh --upgrade   # Move every package to its newest release
pip install -r requirements-dev.txt
```

The script compiles inside the production base image, so the locks resolve for Linux and Python 3.14 whatever machine runs it.

---

## Stop Development Mode

Stop development servers and database.

### Stop Database + Redis (Dev)

```bash
CTRL+C
docker compose --env-file .env.dev -f docker-compose.dev.yml down
```

### Stop Backend and Frontend (Dev)

Press `CTRL+C` in each terminal.

---

# Testing

Backend and frontend unit tests need no environment file. Integration and E2E tests use the committed `.env.test` (see [Environment Files](#environment-files)).

## Backend Tests

From `backend/`:

```bash
./run_tests.sh unit          # Fast: in-memory SQLite, no Docker
./run_tests.sh integration   # Real MySQL + Redis from docker-compose.test.yml
./run_tests.sh combined      # Both, with one merged coverage report
./run_tests.sh help          # All options
ruff check .                # Lint
```

Integration runs start the test containers on ports 3307 (MySQL) and 6380 (Redis), wait for them to be healthy, and remove them afterwards. A bare `pytest` runs the unit tests only.

Unit runs fail below 95% coverage of `app/`, branches included, in total or for any one package (`backend/.coveragerc`, `run_tests.sh`), and any warning fails a test (`backend/pytest.ini`), so a deprecation gets fixed when it first appears rather than when the next major release removes it. Tests run in a new random order each time (`pytest-randomly`); to replay a failing order, pass the seed printed in the header: `pytest --randomly-seed=<seed>`.

## Frontend Tests

From `frontend/`:

```bash
npm run lint          # ESLint
npm run test:run      # Run unit tests once
npm run test          # Watch mode (auto re-runs on changes)
npm run test:coverage # Unit tests with coverage (coverage/ folder); what CI runs
```

Coverage below the thresholds in `vite.config.js` fails the run. Tests run in a shuffled order; replay one with `npx vitest run --sequence.seed=<seed>`, using the seed printed at the start of the run. A test also fails if React reports a state update outside `act()`, which means it asserted before the page settled: await the final state with `findBy*` or `waitFor`. Tests that fake the network build responses from `src/test/fixtures.js`, whose list of error codes is checked against the backend's, and start MSW with `setupMswServer` from `src/test/server.js`; a feature keeps its own fake responses and handlers in its `__tests__/fixtures.js`. Pages are rendered through the real router and `AuthProvider` with `renderRoutes` from `src/test/router.jsx`, and `signIn()` stores a session the way logging in does.

## End-to-End Tests

Playwright drives a real browser against the full stack: Nginx, Flask, MySQL, and Redis from `docker-compose.test.yml`, served at `https://localhost:8443`. It needs Docker and a certificate in `nginx/certs/` (see [SSL/HTTPS Setup](#sslhttps-setup)).

From `frontend/`:

```bash
npx playwright install chromium   # First time only
npm run test:e2e                  # Builds and starts the stack, then runs the tests
npm run test:e2e:ui               # Interactive mode
```

Locally, Playwright reuses a test stack that is already running (for quick reruns while editing tests), even if the app code has changed since it was built. After changing app code, or after an interrupted run, stop it first, and again when done, from the repository root:

```bash
docker compose --env-file .env.test -f docker-compose.test.yml --profile e2e down -v
```

`accessibility.spec.js` runs [axe](https://github.com/dequelabs/axe-core) on every shared page, busy and failed states included, against the WCAG 2.2 A and AA rules, catching what jsdom cannot, such as color contrast. It also checks what axe cannot: reflow at 320px, visible focus, target size and focus after back and forward. Each feature's spec does the same for its own pages.

## Continuous Integration

GitHub Actions (`.github/workflows/`):

* **CI** (`ci.yml`) runs lint and the backend and frontend unit suites, runs them again after deleting the example code as [Starting a New App](#starting-a-new-app-from-this-template) describes (`.github/scripts/remove_examples.py`), validates all three compose files, lints the workflows and Dependabot config (zizmor) and both Dockerfiles (hadolint), checks that `LICENSE` exists and that the list of required status checks below names every job (`.github/scripts/check_required_checks.py`), refuses trailing whitespace (outside Markdown) and a missing final newline in any tracked file (`.editorconfig` sets editors to match), and checks the rendered nginx config (`nginx -T`, then the gixy-ng security analyzer), on every push and pull request to `main`.
* **Integration & E2E** (`integration-e2e.yml`) runs the integration and Playwright suites, and a smoke test of the layout a container platform runs (the backend and nginx in `behind-proxy` mode sharing one network namespace), on every push and pull request to `main`, nightly to catch drift in base images, and on demand from the Actions tab.

Every job has a read-only token and a timeout, and actions are pinned to commit SHAs.

Dependabot (`.github/dependabot.yml`) opens weekly update PRs for the Python locks, npm, Docker images and GitHub Actions. For it to also open security fixes as soon as an advisory is published, enable Dependabot alerts and security updates under the repository's Settings > Advanced Security.

To stop a failing check from merging, require these status checks on `main` (Settings > Branches): Backend unit, Frontend unit, Scaffold, Compose files, Workflows, Dockerfiles, Nginx config, Backend integration, Platform smoke and Playwright E2E.

---

# SSL/HTTPS Setup

Nginx serves the app over HTTPS only (port 80 redirects to 443), so it needs a certificate in `nginx/certs/` before it will start: `fullchain.pem` and `privkey.pem`. The production and test stacks mount that folder into the container.

## Self-Signed Certificate (local production testing and E2E)

```bash
mkdir -p nginx/certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/certs/privkey.pem \
  -out nginx/certs/fullchain.pem \
  -subj "/C=US/ST=California/L=San Francisco/O=Dev/CN=localhost"
```

Visit `https://localhost` and bypass the browser security warning (expected for self-signed certs). For local production testing, set `SERVER_NAME=localhost` in `.env.prod`.

On a server, keep the key private: `chmod 600 nginx/certs/privkey.pem` (openssl already creates it that way). The nginx container can still read it, whoever owns it on the host.

## Real Domain (Let's Encrypt)

```bash
# 1. Install Certbot on your server
sudo apt install certbot  # Ubuntu/Debian

# 2. Obtain a certificate (port 80 must be free, so stop the stack first)
sudo certbot certonly --standalone -d yourdomain.com -d www.yourdomain.com
```

3. In `docker-compose.yml`, replace the nginx volume `./nginx/certs:/etc/nginx/certs:ro` with the whole Certbot directory. Its `live/` files are relative symlinks into `archive/`, so mounting only `live/` breaks them.

   ```yaml
   volumes:
     - /etc/letsencrypt:/etc/letsencrypt:ro
   ```

4. In `.env.prod`, set `SERVER_NAME=yourdomain.com www.yourdomain.com`. In `nginx/servers/tls.conf.template`, point the certificate at Certbot's paths:

   ```nginx
   ssl_certificate      /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
   ssl_certificate_key  /etc/letsencrypt/live/yourdomain.com/privkey.pem;
   ```

5. Rebuild and restart: `docker compose --env-file .env.prod up -d --build`

Let's Encrypt certificates expire after 90 days. Renew with `certbot renew` (the standalone method needs port 80 free, so stop nginx first), then restart nginx.

---

# Production Mode (Docker)

Run your web application in a consistent, production-like environment.

**Architecture (Prod)**

* MySQL → Docker, or external ([External Database or Redis](#external-database-or-redis))
* Redis → Docker, or external
* Flask (Gunicorn) → Docker
* React → Built & served by Nginx

Only Nginx is published (ports 80 and 443). Nginx reaches only Flask; the bundled MySQL and Redis sit on an internal network with no outbound access, reachable only from Flask. Every container runs with `no-new-privileges`, Flask on a read-only filesystem with no Linux capabilities. Redis's `default` user is disabled; the app connects as an ACL user limited to its own keys, with dangerous commands (FLUSHALL, CONFIG, KEYS, ...) refused.

---

## Build and Start

Requires `.env.prod` and a certificate in `nginx/certs/` (see above).

```bash
docker compose --env-file .env.prod up --build
```

A one-shot `migrate` container applies migrations as the migration user and exits. The backend then starts Gunicorn as the app's user, whose credentials cannot change the schema (see [Database users](#environment-files)), and nginx starts once the backend passes its health check.

**When to rebuild:** frontend and backend code are both copied into their images, so rerun with `--build` after any code change.

**Deploying a change to a running app:** a single `up -d --build` replaces the backend before `migrate` runs, so if `migrate` fails (a bad migration, a wrong password, an unreachable database), the app is down until it is fixed. Build and migrate first instead; the running app keeps serving through both, and each command stops the deploy if it fails:

```bash
docker compose --env-file .env.prod build \
  && docker compose --env-file .env.prod up --exit-code-from migrate migrate \
  && docker compose --env-file .env.prod up -d --wait
```

The last command replaces the backend and nginx, so requests get a 502 or 504, or a refused connection, for a few seconds. A migration must keep the old code working, since the old backend serves after it runs ([Deploying to a Platform](#deploying-to-a-platform), Migrations).

**Production URL:** `https://<SERVER_NAME>` ([https://localhost](https://localhost) when testing locally with `SERVER_NAME=localhost`).

---

## External Database or Redis

The bundled MySQL and Redis containers are optional: production can use a MySQL 8 database and a Redis (or Valkey) server that run elsewhere, such as Amazon RDS and ElastiCache. Each one is switched on its own, with no code change:

1. Remove its profile from `COMPOSE_PROFILES` in `.env.prod` (`bundled-db`, `bundled-redis`), so its container no longer runs.
2. Set its URLs in `.env.prod`: `DATABASE_URL` and `MIGRATION_DATABASE_URL` for the database, `REDIS_URL` for Redis (the example file's last lines show their shape). They replace the URLs `docker-compose.yml` would build. The bundled values it no longer uses can stay; Compose warns about each one you remove.

Each managed service is a processor of your users' data: see [Personal Data and Legal Pages](#personal-data-and-legal-pages), "Before launch", step 3.

`migrate` and the backend reach an external service through the `edge` network, the one with a route out of the host.

**TLS is required.** Production treats any host other than the bundled services' names, `db` and `redis`, as outside the server, and refuses to start unless the connection is encrypted and checks the server's certificate and name. Keep those two names if you rename the services.

* The database URL needs `?ssl_ca=<path>`, a CA bundle inside the container. A database whose certificate comes from a public CA can use the image's own bundle, `/etc/ssl/certs/ca-certificates.crt`. Amazon RDS's CAs are not in it: download RDS's bundle (`https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem`) and mount it, read-only since the image is, in a `docker-compose.override.yml` beside `docker-compose.yml`, which Compose reads automatically:

  ```yaml
  services:
    migrate:
      volumes: ["./certs/rds-global-bundle.pem:/etc/ssl/rds.pem:ro"]
    backend:
      volumes: ["./certs/rds-global-bundle.pem:/etc/ssl/rds.pem:ro"]
  ```

  and end both database URLs with `?ssl_ca=/etc/ssl/rds.pem`.
* The Redis URL must start with `rediss://`. ElastiCache's certificates chain to Amazon's public roots, which the image's bundle holds, so it needs nothing more; for another CA, add `?ssl_ca_certs=<path>`.
* Options that could switch either check off (`ssl_check_hostname`, `ssl_verify_cert`, `ssl_verify_identity` and `ssl_disabled` in the database URL; `ssl_cert_reqs` and `ssl_check_hostname` in the Redis URL) are refused.

**Two database users.** Create them as the provider's admin user, as the MySQL image and `db/init/01-app-user.sh` do for the bundled MySQL:

```sql
CREATE DATABASE appdb;
CREATE USER 'app_migrate'@'%' IDENTIFIED BY '<migration password>' REQUIRE SSL;
GRANT ALL PRIVILEGES ON `appdb`.* TO 'app_migrate'@'%';
CREATE USER 'app'@'%' IDENTIFIED BY '<app password>' REQUIRE SSL;
GRANT SELECT, INSERT, UPDATE, DELETE ON `appdb`.* TO 'app'@'%';
```

The database name may hold only letters, digits and `_`, and `_` is a wildcard in `GRANT`: write `app\_db` for `app_db`, since the start check refuses the unescaped form, which covers other databases too. On start-up in production, the backend and `migrate` read the grants of `DATABASE_URL`'s user and refuse to start if it holds anything beyond `SELECT`, `INSERT`, `UPDATE` and `DELETE` on its database (`USAGE` on `*.*`, MySQL's name for none, is fine): no schema rights, no rights on every database or on any other one (MySQL's own grant tables, another app's), no role and no `WITH GRANT OPTION`. There is no opt-out: a provider that offers a single database user is not supported. The admin user stays with you; neither container ever gets it.

**Redis settings the app cannot check.** Its ACL user may not read the server's configuration, so set these yourself:

* `maxmemory-policy noeviction`. Every refresh token carries an expiry, so a policy that evicts keys with one (ElastiCache's default, `volatile-lru`) silently signs users out once memory fills. On ElastiCache, use a custom parameter group.
* A user named in `REDIS_URL` (required), with the bundled ACL's rules: on ElastiCache, an RBAC user with the access string `on ~refresh_tokens:* ~LIMITS:* +@all -@dangerous`. An AUTH token alone, on the `default` user, is refused.
* Cluster mode disabled: the app's Redis client is not cluster-aware. That rules out ElastiCache Serverless, which is always clustered and whose eviction policy is fixed at `volatile-lru`; use a node-based cluster.

**Network access.** Let only the server reach the database and Redis (security groups, a private network, or the provider's allowlist), never the internet.

**Passwords in URLs** must be percent-encoded; the generator in [Environment Files](#environment-files) only produces characters that need none. With Compose the password must be in the URL; on a platform it can come from its own variable instead (`DATABASE_PASSWORD`, `MIGRATION_DATABASE_PASSWORD`, `REDIS_PASSWORD`), which needs no encoding.

The backend gives up on a DNS lookup after one try of 1 second (`dns_opt`, so a stopped bundled service fails fast). Pooled connections are reused, so an external host is looked up rarely, but a slow resolver can fail a request that needs a new connection.

---

## Deploying to a Platform

The Compose stack is one way to run the app. The same two images also run on a container platform (Amazon ECS on Fargate, Kubernetes, Google Cloud Run with sidecars), with managed MySQL and Redis ([External Database or Redis](#external-database-or-redis)). Nothing in the images depends on Compose: what they read from the environment is the whole contract, and `.env.prod` is only Compose's way of supplying it. The platform and each managed service it adds (a database, Redis, a log service, a CDN) are processors of your users' data: see [Personal Data and Legal Pages](#personal-data-and-legal-pages), "Before launch", step 3.

### The Contract

**Images.** Build both for the platform's CPU (`--platform linux/amd64`, or `linux/arm64` for Graviton) and tag them with the commit:

```bash
docker build --platform linux/amd64 -t <registry>/app-backend:<sha> backend
docker build --platform linux/amd64 -f nginx/Dockerfile -t <registry>/app-nginx:<sha> .
```

| | backend | nginx |
|---|---|---|
| Port | 5000 (gunicorn) | 80 (`behind-proxy`) |
| Environment | `APP_ENV=production`, `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`; optionally `DATABASE_PASSWORD`, `REDIS_PASSWORD`, `WEB_CONCURRENCY` (about one per vCPU), `TRUSTED_PROXY_COUNT` | `NGINX_MODE=behind-proxy`, `NGINX_SERVER_NAME` (your domain), `NGINX_TRUSTED_PROXIES` (the load balancer's subnets), `NGINX_BACKEND_ADDRESS=127.0.0.1` |
| Filesystem | read-only root, plus a writable `/tmp` (gunicorn's worker heartbeats) | writable: it renders its config into `/etc/nginx/conf.d` at start |
| Health | `GET /api/health` on 5000. Allow 60 s to start: it waits up to 60 s for MySQL and Redis, then checks its database user's grants | none of its own; the load balancer checks `/api/health` through it |

**Secrets.** Keep each URL without its password in plain configuration, and inject `DATABASE_PASSWORD`, `REDIS_PASSWORD` and `SECRET_KEY` from the platform's secret store. Each password variable replaces its URL's password.

**Migrations** run once per deploy, before the new backend starts: the backend image with the command `flask db upgrade`, plus `MIGRATION_DATABASE_URL` (its password inline or in `MIGRATION_DATABASE_PASSWORD`; the variable alone does nothing) and `DB_QUERY_TIMEOUT=0`. Give that job its own task or job definition, so the long-running backend never holds the migration user's credentials. Rolling deploys run old and new backends side by side for a while, so a migration must keep the old code working: add a column in one release, and drop the old one in a later release.

**The client's address.** The load balancer terminates TLS and sends nginx plain HTTP with `X-Forwarded-For`. nginx trusts that header only from `NGINX_TRUSTED_PROXIES` and forwards the result to the backend, whose `TRUSTED_PROXY_COUNT` stays 1. Get the range wrong, and either every user shares the balancer's address (one rate-limit bucket, so one user can lock everyone out), or a client can choose its own address. Set `TRUSTED_PROXY_COUNT` only if you leave nginx out: 1 behind a load balancer, 2 with a CDN in front of it.

**Keep nginx in front of the backend.** It's the layer the E2E suite and the audits test: security headers and CSP, the 16 KB body cap, per-IP rate limits, JSON error bodies and unknown-host refusal. It costs about 10-20 MB per task. Replacing it means rebuilding all of that in the load balancer or CDN. Its per-IP limits count per task, so three tasks give one client three times the budget. The backend's own limits (login, register, refresh, account deletion) count in Redis and stay exact. For exact limits at the edge, use the load balancer's WAF.

CI's Platform smoke job runs this layout (the backend and a `behind-proxy` nginx sharing one network namespace) and checks health, headers, the body cap, the HTTPS redirect and the client's address. Only the Compose stack gets the full E2E suite.

### What Replaces Each Compose Piece

| Compose | On a platform |
|---|---|
| `.env.prod` | the task definition's environment, plus the secret store |
| `db`, `redis` (bundled profiles) | managed MySQL and Redis: [External Database or Redis](#external-database-or-redis) |
| `migrate` and `depends_on` | a one-off task run by the deploy before the service updates |
| nginx in `tls` mode, `nginx/certs/` | a load balancer with a managed certificate, and nginx in `behind-proxy` mode |
| the backend's fixed `edge` address, `dns_opt` | `127.0.0.1`: containers in one task share a network namespace. Both are Compose-only |
| the `edge` and `internal` networks | private subnets and security groups |
| healthchecks, `restart` | the platform's container health checks and service scheduler |
| `deploy.resources` | the task's CPU and memory |
| `x-logging` rotation | the platform's log service and its retention |
| `cap_drop`, `read_only`, `no-new-privileges`, `pids_limit` | the task definition's equivalents, where the platform has them |

### Example: Amazon ECS on Fargate

A sketch of one working layout, not infrastructure code. Translate it into your own tooling (console, CloudFormation, Terraform, CDK).

1. **Images:** push both to ECR.
2. **Database and Redis:** RDS for MySQL 8 and ElastiCache for Redis OSS or Valkey (node-based, cluster mode off), set up as [External Database or Redis](#external-database-or-redis) describes. On Fargate there's no host to mount the RDS CA bundle from. It's public, so copy it into your app's backend image (`COPY certs/rds-global-bundle.pem /etc/ssl/rds.pem`).
3. **Secrets:** `SECRET_KEY`, `DATABASE_PASSWORD`, `MIGRATION_DATABASE_PASSWORD` and `REDIS_PASSWORD` in Secrets Manager, referenced from the task definitions' `secrets`.
4. **The service's task definition** (`awsvpc`; start at 1 vCPU and 2 GB):
   - `backend`: port 5000, `readonlyRootFilesystem: true` with a volume at `/tmp`, `linuxParameters.capabilities.drop: ["ALL"]`, and a health check running the same command as `docker-compose.yml`'s with `startPeriod: 60`.
   - `nginx`: port 80, `dependsOn` backend `HEALTHY`, with the `behind-proxy` variables above (`NGINX_TRUSTED_PROXIES` set to the ALB's subnets). Fargate can't add capabilities, so leave nginx's default set rather than dropping them all.
   - Both log through `awslogs` to CloudWatch Logs groups with a retention you choose ([Logs](#logs)).
5. **Migrations:** a second task definition, the backend image only, with the command and variables from "Migrations" above. The deploy runs it (`aws ecs run-task`), waits for exit code 0, then updates the service.
6. **Load balancer:** an ALB with an ACM certificate. The HTTPS listener forwards to the service's port 80, and the HTTP listener redirects to HTTPS. The target group's health check is `/api/health`, and the service's health-check grace period is at least 60 s.
7. **Security groups:** the ALB accepts 80 and 443 from the internet. The tasks accept port 80 from the ALB only, never 5000 (gunicorn listens on every interface inside the task). RDS and ElastiCache accept connections from the tasks only.

**Optional: the frontend on S3 and CloudFront.** Upload `frontend/dist` to a private S3 bucket behind CloudFront, and add a CloudFront behavior that sends `/api/*` to the ALB, so the browser still calls a same-origin `/api`. Set that behavior to:

- no caching (`CachingDisabled`);
- forwarding the viewer's `Host` (`AllViewer`), or nginx drops the request.

Then:

- Copy nginx's page headers into a response headers policy (the CSP and `Permissions-Policy` from the `/` location in `nginx/app_server.conf`; HSTS, `X-Frame-Options`, `X-Content-Type-Options` and `Referrer-Policy` from `nginx/security_headers.conf`), and its caching too: `index.html` `no-cache`, `/assets/*` cached for a year.
- Route unknown paths to `index.html` with a CloudFront Function on the S3 behavior, not with custom error responses: those apply to the whole distribution and would turn the API's 404s into the page.
- Let only CloudFront reach the ALB, and add CloudFront's origin-facing ranges (AWS's `ip-ranges.json`, `CLOUDFRONT_ORIGIN_FACING`) to `NGINX_TRUSTED_PROXIES`, or every client gets a CloudFront edge's address.
- Add AWS WAF on CloudFront for exact edge rate limits.

---

## Logs

Every container logs to stdout, which Docker keeps, rotated at three files of 10 MB each (`x-logging` in `docker-compose.yml`):

```bash
docker compose --env-file .env.prod logs -f nginx backend
```

The backend's lines (the app's, gunicorn's, the start-up wait's and the one-shot `migrate` service's) and nginx's access log are one JSON object per line. nginx's error log (an unreachable backend, an oversized body) is plain text, and so is the second copy of the exception gunicorn prints when a worker fails to boot.

nginx logs one request in 100 that it refuses for a client's rate (a 429), and every other request. A client flooding the API writes a few sampled lines a second instead of thousands, which would push every earlier line out of Docker's 30 MB in seconds; multiply the sampled lines by 100 for the flood's size. A single 429 a real user got is likely not in the log.

nginx's access log is the one record of each request: the client's address, the request's path, its status and how long it took. The path is logged without its query string, where a link's token would sit, and cut at 512 characters; the User-Agent and Referer are cut at 256. Each line has a `request_id`, which nginx also hands the backend: every backend line written during that request carries the same one, which joins the two.

The backend logs errors, and security events on the `app.security` logger: `login_succeeded`, `login_failed`, `registered`, `refresh_refused` (an old refresh token used again, as a stolen cookie would be), `token_invalid` (a token the app never issued, a refresh token sent as an access token, a refresh cookie without its CSRF value, or a deleted account's token), `logout`, `logout_all`, `wrong_password` (a wrong password when deleting the account), `account_deleted` and `rate_limited`. Each names the client by address, and the user by id where there is one (`rate_limited` gives the path and the limit instead). A failed login names the account by `account`, a keyed hash of its email, so one guessed-at address can be followed across IPs without the log holding it. No line holds a password, token or email.

Two of these events have innocent causes too. `refresh_refused` is a lead, not proof: a refresh whose answer never reached the client (a 504 on `/api/auth/refresh` from the same address just before) has already rotated its token, so the client's next refresh is refused the same way. And after a `SECRET_KEY` rotation, every token signed with the old key logs `token_invalid` once.

Shipping logs off the server, and how long to keep them, is up to the deployment. Until they are shipped, Docker's three files per container are all there is. Their lines pair IP addresses with user ids, which is personal data: choose how long to keep them, say so in the privacy notice, and enforce it by age where the logs are shipped ([Personal Data and Legal Pages](#personal-data-and-legal-pages)). nginx caps each line and how fast one address can add them, pages and API alike, which makes pushing older lines out slow for one client but not impossible for many.

---

## Stop Production App

```bash
CTRL+C
docker compose --env-file .env.prod down
```

---

## Full Reset (⚠️ Deletes Database)

Stops everything and **removes this project's volumes (data loss)**:

```bash
docker compose --env-file .env.prod down --volumes --remove-orphans
```

---

# Summary

| Mode | DB | Redis | Backend | Frontend |
|------|----|-------|---------|----------|
| Prod | Docker or external | Docker or external | Docker | Docker (Nginx) |
| Dev | Docker | Docker | Local | Local |
| Unit tests | SQLite in memory | Not used | Local | Local (jsdom) |
| Integration tests | Docker | Docker | Local | n/a |
| E2E tests | Docker | Docker | Docker | Docker (Nginx) |

---

# Personal Data and Legal Pages

Every app built from the template collects personal data from its first sign-up, so it ships placeholder legal pages that each app must write for itself. None of this is legal advice: have a lawyer review the pages before launch.

**What ships:**
- `/privacy`, `/terms` and `/contact` (`frontend/src/pages/`), linked from the footer of every page. Each opens with a placeholder notice and gives one heading per topic, with what to write in brackets.
- `frontend/src/legal.js`: the operator's name, address and contact email, which the pages show, and `TERMS_VERSION`.
- A required checkbox on the register form, "I accept the Terms and the Privacy notice". The form sends the version it showed, the backend refuses any but the current `TERMS_VERSION` (`backend/app/auth/models.py`) with a 409 `TERMS_OUTDATED`, and `users` records `terms_version` and `terms_accepted_at`.
- `frontend/public/.well-known/security.txt` (RFC 9116), where to report a security problem.

**What the template keeps about people:**

| Data | Where | How long |
|---|---|---|
| Email, password hash, when registered, terms version and when accepted | MySQL `users` | Until the user deletes the account (Account page) |
| Users' content (the notes example) | The feature's tables | Until the user deletes it or the account |
| Every write, deleted rows included | MySQL's binary log | 30 days (MySQL's default) |
| Refresh-token ids, at most 10 per user | Redis | Until the session expires (7 days idle, 30 at most), logs out or deletes the account |
| Rate-limit counters: per IP, per keyed hash of an email, per user | Redis | A minute to an hour |
| Access log: IP, path (no query string), status, timings, User-Agent, Referer | nginx's stdout, kept by Docker | Until Docker's 3 × 10 MB rotate out |
| Security events: IP, user id; a keyed hash of the typed email on a failed login | The backend's stdout, kept by Docker | The same |
| Access token, refresh CSRF value, email | The browser's `localStorage` | Until logout or the session ends |
| Refresh token | Cookie `__Secure-refresh_token` (HttpOnly) | Up to 30 days |

Deleting an account (the Account page asks for the password) deletes its `users` row, every feature's rows that reference it, and its sessions in Redis, at once. What the logs and MySQL's binary log hold about it goes as they age out, and so would its copies in backups, by their own retention: state that in the privacy notice.

No analytics, no third-party requests and no email: the template itself sends nothing to a third party, though your host and any managed service you add are processors. The cookie and `localStorage` are strictly necessary for the login the user asked for, so no consent banner is needed.

**Before launch:**
1. Fill in `legal.js`, then write the three pages for your app from the table above and your own features.
2. Choose how long to keep logs (France's CNIL suggests 6 to 12 months for security logs), state it in the privacy notice, and enforce it by age once logs are shipped. Decide the MySQL binary log together with backups: keep it for point-in-time recovery, or turn it off.
3. Name every provider that processes personal data for you (the host, a log service, a CDN, an email service) in the privacy notice, and sign each one's data processing agreement. If one processes EU or UK users' data outside the EU/EEA or UK, note the transfer safeguard in the notice (an adequacy decision, or the standard contractual clauses in its agreement), or choose a region inside.
4. Set `security.txt`'s `Contact` to the email in `legal.js` (a test checks they match) and `Expires` to under a year away, and renew `Expires` every year (the same test fails from 30 days before it lapses).
5. Ask the lawyer whether your markets need a checkbox or whether a sentence beside the button would do, and whether a German audience needs the contact page labelled "Impressum" with more details on it.
6. Check whether the European Accessibility Act covers your service (e-commerce, banking and a few other sectors; microenterprises are exempt).
7. When the terms change, raise `TERMS_VERSION` in both `legal.js` and `backend/app/auth/models.py`. Asking existing users to accept the new terms is your app's job.

**Duties that start with a feature:**
- **Content other users can see** (sharing, profiles, comments, uploads): a way to report illegal content (EU Digital Services Act, Art. 16), and in the US a DMCA agent and a repeat-infringer policy.
- **Children:** an audience under 13, or knowing that a user is, brings COPPA, and consent-based processing the GDPR's age of consent.
- **Email** (verification, password reset, newsletters): CAN-SPAM, PECR and CASL.

---

# Starting a New App From This Template

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

   Either way, delete `backend/migrations/versions/0002_notes.py` (step 4 generates yours) and update the wiring points above. Then delete `.github/scripts/remove_examples.py` and the Scaffold job in `.github/workflows/ci.yml`, and drop Scaffold from the status checks required on `main` ([CI](#continuous-integration)): they only prove that the template's examples can be removed, and the import rules keep shared code off your features.
3. Remove the API-status demo, unless you want it: delete `frontend/src/features/health/` and `frontend/e2e/api-status.spec.js`, the `ApiStatus` import and element in `frontend/src/pages/HomePage.jsx`, and the `vi.mock` of `ApiStatus` in `frontend/src/pages/__tests__/HomePage.test.jsx`, with `vi` in its import.
4. Generate a migration for your tables. From `backend/`, with `.env.dev` loaded as in [Database Schema Changes](#database-schema-changes-during-dev). If the dev backend ran after step 1 while `0002_notes.py` still existed, the database refers to a migration that is gone: reset it first (`docker compose --env-file .env.dev -f docker-compose.dev.yml down -v`, then start it again).

   ```bash
   flask db upgrade
   flask db migrate -m "<your feature>" --rev-id 0002_<your_feature>
   ```

   Upgrade first: Alembic only writes a migration against an up-to-date database. In the generated file, keep only the `op.drop_table(...)` lines in `downgrade()`: MySQL will not drop an index that a foreign key uses, and dropping the table drops its indexes anyway. Then run `./run_tests.sh integration`, whose `test_migrations.py` checks that the migrations match the models and undo cleanly.
5. Name the app, without using anyone else's trademark: `APP_NAME` in `frontend/src/appName.js` and the `<title>` in `frontend/index.html` (a test checks they match). Replace the placeholder icon, `frontend/public/favicon.svg`.
6. Rewrite this README and `CLAUDE.md` for your app, and choose its license: replace `LICENSE` and the `license` field in `frontend/package.json` (the template is MIT-0, so your app owes it no notice). Delete `.claude/skills/audit-scaffold/`, which acts out these steps on the template; keep the other audits in `.claude/skills/` and update their references to notes, or delete them.
7. Write the legal pages and work through the list under [Personal Data and Legal Pages](#personal-data-and-legal-pages), "Before launch".

# License

MIT-0 (MIT No Attribution), see [`LICENSE`](LICENSE): reuse the template without keeping any notice. The production build also writes the bundled libraries' own notices to `third-party-licenses.txt`, which nginx serves beside the app.
