---
name: audit-infra
description: Review config and infrastructure at every layer (env, nginx, Docker/Compose, Flask, MySQL, Redis, React build, CI) for correctness, security, simplicity and template-readiness, plus performance bottlenecks. The daily check.
argument-hint: "[layer: env|nginx|docker|flask|mysql|redis|frontend|ci|perf]"
disable-model-invocation: true
context: fork
---

# /audit-infra

First read `.claude/skills/_audit-shared/RULES.md` and follow it throughout.
Then read `CLAUDE.md`, plus `SOURCES.md` and `DECISIONS.md` from the same
folder as RULES.md. This check runs Docker: record all four Timings
(RULES.md, Report).

**Scope:** `$ARGUMENTS`. If empty, cover every layer below. If it names
layers, cover only those.

For each layer: read every file listed, check each CLAUDE.md claim about that
layer against the code, compare the layer with its SOURCES.md section, then
work through the questions. Questions that ask whether something exists ("a
health check on every service") are prompts, not requirements: under RULES.md's
lean rule, a missing piece is a finding only if something would act on it or
its absence causes a real failure.

**Running stacks:** bring up the E2E test stack once (RULES.md) and use it for
every live check below: startup logs of **every** service
(`docker compose ... logs`, looking for errors and warnings), live privileges,
and the perf timings. Use the production-config stack only for a question
whose answer depends on production-only settings (persistent volumes, restart
policies, the production database name, `ProductionConfig`), and say in the
report which questions needed it. The questions are starting points, not the limit.
Report anything a senior engineer would flag on review.

## Layers

### env: environment and config selection
Files: `.env.dev`, `.env.test`, `.env.prod.example`, `backend/app/config.py`,
`backend/wait_for_services.py`, `db/init/01-app-user.sh`, every
`environment:` block in the three compose files, `.gitignore`, `.dockerignore`,
`backend/.dockerignore`.
- Is every variable in an env file read by something (`os.getenv`, or `${VAR}`
  in a compose file)? Is any set to its code default (redundant)?
- Does every variable the app requires reach it in each environment
  (CLAUDE.md's Naming Conventions table)? Are they listed explicitly, never via
  `env_file:`? Does only the `migrate` service get the root password?
- Does `APP_ENV` alone select the config class? Can anything else promote or
  demote one? Does `ProductionConfig` reject weak or placeholder secrets, and
  is that tested?
- Do `.env.dev` and `.env.test` hold only obviously throwaway values? Is
  `.env.prod` untracked (`git ls-files .env.prod` empty)?
- Ignores: does each ignore file cover what exists in this repo (venvs, caches,
  coverage, reports, certs, `.env.prod`, keys) and nothing speculative? Do
  Docker build contexts exclude env files, tests and certs? Run
  `git status --porcelain --ignored` and flag sensitive-looking files.

### nginx
Files: `nginx/` (Dockerfile, `nginx.conf`, `proxy_params.conf`,
`security_headers.conf`, `resource_headers.conf`, `templates/`).
- Compare TLS settings with the Mozilla "intermediate" profile, and headers and
  caching with h5bp `server-configs-nginx`. Is the CSP as strict as the
  built app allows (check `frontend/index.html` and the build output for inline
  scripts and styles)?
- Does every `location` that sets `add_header` include `security_headers.conf`,
  directly or through `resource_headers.conf`?
- Body cap, rate and connection limits, and JSON error bodies: consistent with
  Flask's limits and the API's error shape?
- Catch-all server, HTTP→HTTPS redirect, the upstream at the backend's fixed
  address with no DNS (`00-upstream.conf.template` against the compose
  files' `EDGE_SUBNET_PREFIX`), timeouts and keepalive in line with
  gunicorn's settings?

### docker: images and Compose
Files: `backend/Dockerfile`, `backend/entrypoint.sh`, `nginx/Dockerfile`,
`docker-compose.yml`, `docker-compose.dev.yml`, `docker-compose.test.yml`.
- Base images pinned and current (MySQL, Redis, Python, Node, nginx all
  supported releases)? Multi-stage builds, non-root users, minimal layers?
- Production: health checks on every service, restart policies, resource
  limits, `stop_grace_period` ≥ the app's graceful timeout, log rotation,
  `no-new-privileges`, `cap_drop`, `read_only` where possible, and an
  `internal` network that nginx cannot reach?
- Does the test stack mirror production's hardening, so E2E catches breakage?
- Do image majors match the CI runtimes (`setup-node`, `setup-python`
  versions in `.github/workflows/`) and each other? Are they all supported
  (not end-of-life) releases?
- Are dev, test and production consistent in naming (CLAUDE.md table) and
  image versions?

### flask: application
Files: `backend/app/__init__.py`, `config.py`, `features.py`, each feature's `routes.py`, `utils/`, `wsgi.py`,
`backend/requirements.in`.
- Do app factory, extension setup, error handlers and the JWT loaders match
  CLAUDE.md (fail closed, user loader, error shape)?
- Are timeouts, pool settings and Redis client options set so an outage fails
  fast instead of hanging?
- Is anything example-feature specific leaking into shared code?

### mysql
Files: each feature's `models.py` (`backend/app/*/models.py`), `backend/migrations/`, the `db` services.
- Indexes for every query pattern (grep the routes for filters and orderings),
  constraints and `ON DELETE` behavior, column sizes matching the named
  constants, UTC session time zone, `pool_pre_ping` or recycle settings.
- Do migrations match the models (`test_migrations.py` checks this; is it
  green in CI)?
- Least privilege, checked live on the running stack: `SHOW GRANTS` for the
  app user, then try `CREATE TABLE` and `DROP TABLE` as that user. Do not
  trust `db/init/01-app-user.sh`'s output or `test_db_users.py`. Which
  containers hold which database password (the root's only `db`, the
  migration user's only `db` and `migrate`)?
- MySQL server settings worth setting explicitly (character set, SQL mode)?
  Startup warnings from the `db` logs.

### redis
Files: `backend/app/utils/redis_service.py` (and the rest of `utils/`), the
`redis` services.
- ACL user scope (key patterns, `-@dangerous`), `noeviction`, `maxmemory`,
  persistence settings in production vs what losing Redis would cost
  (sessions and rate limits), key TTLs so nothing grows without bound.

### frontend: build and runtime config
Files: `frontend/vite.config.js`, `package.json`, `index.html`,
`eslint.config.js`, `jsconfig.json`, `src/main.jsx`, `src/routes.jsx`,
`src/api/api.js`.
- Production build: run `npm run build -- --outDir <scratch>/dist` in
  `frontend/` and look at the output sizes. Are there source maps, dev-only code or unused dependencies in the
  bundle?
- Does `package.json` have runtime vs dev dependencies in the right place,
  and scripts that match CLAUDE.md? Is the Node version consistent wherever
  it is set (CI, Dockerfile, any `engines` field)?

### ci: workflows and supply chain
Files: `.github/workflows/`, `.github/dependabot.yml`, `backend/lock_deps.sh`,
`backend/requirements*.in/.txt`.
- Actions pinned by SHA, least `permissions:`, `persist-credentials: false`,
  timeouts, no untrusted input interpolated into `run:`?
- Does every check CLAUDE.md says CI runs actually run? Is anything run twice?
- Read the latest runs (`gh run list --branch main --limit 20`, which also
  shows GitHub-managed workflows such as Dependabot and code scanning). Any
  red, flaky (failed then passed on retry), or slow jobs?
- Open Dependabot PRs (`gh pr list --author app/dependabot`): does any of them
  propose a version the project should not take (an end-of-life or
  odd-numbered Node, a major the tools don't support)? If so, the fix is an
  `ignore` rule in `dependabot.yml`.

### perf: bottlenecks
- Request path cost: queries per request (N+1), missing indexes, unbounded
  lists, password hashing cost vs worker and thread counts
  (`PASSWORD_HASH_CONCURRENCY`, `WEB_CONCURRENCY`), Redis round trips per
  request, nginx buffering and keepalive.
- Frontend: bundle size, waterfalls, polling intervals, re-renders on hot
  paths.
- Estimate the first bottleneck under load (which resource saturates first,
  roughly at what request rate) and whether the template documents how to
  scale past it. Keep it light: at most a few hundred requests against the
  local test stack, paced under nginx's per-IP limit (see RULES.md on
  requests from the host). Save the timing script in your report's appendix,
  so the next run can repeat it and compare the numbers.

## Out of scope
Code-level security review and dependency CVEs (`/audit-security`), tests
(`/audit-tests`), comments and dead code (`/audit-code`), README and CLAUDE.md
prose accuracy (`/audit-docs`). Note anything you spot in passing under
*Unverified / Skipped* as "for /audit-…", without investigating.

Write the report as RULES.md describes, with ID prefix `INFRA`.
