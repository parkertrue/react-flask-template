# Audit decisions

Choices an audit would otherwise flag, recorded so every run stops re-raising
them. Each entry says what was chosen and why. A check reports an entry here
only if its **Revisit when** condition has come true, or the code no longer
matches the entry (then the entry is stale and that is the finding).

Add an entry when a finding is deliberately kept as-is. Delete one when the
code changes so it no longer applies.

In a *Revisit when*, "a deployment", "a real server" and "production" mean
one that serves real users and holds their data. A server the maintainer runs
for testing doesn't count, even one that deploys every merge to `main`.

## Accepted trade-offs

**External services: one database user is not enough, and the bundled
services are known by name.** In production the backend refuses to start
when `DATABASE_URL`'s user holds more than row rights (`wait_for_services.py`),
with no opt-out, so a provider that offers a single database user is
unsupported (user's decision, 2026-10-21). TLS is required for any host but
`db` and `redis`, the bundled services' names, so renaming those services
means editing `config.py` too (`docs/deployment.md`, "External Database or Redis"). One gap
stays: a `MIGRATION_DATABASE_URL` set on the backend itself wins over
`DATABASE_URL`, and the app then runs as the schema's owner; only the
compose file's `environment:` lists keep it on `migrate`.
*Revisit when:* a deployment needs a provider with one user, or the backend
is run by something other than the compose file.

**Access token in localStorage.** The 15-minute access token is readable by
any XSS; the refresh token stays in an HttpOnly cookie. Mitigated by the short
expiry, the CSP, and React's escaping. Keeps the client simple: no cookie for
API calls, so no CSRF on them. See the comment in `frontend/src/auth/storage.js`.
*Revisit when:* the app renders third-party or user-supplied HTML.

**Register answers 409 for a taken email.** This tells an attacker an
account exists. Accepted for the clearer sign-up message; register is rate
limited per IP, and login timing no longer leaks it (dummy hash).
*Revisit when:* email verification exists. Then register can answer the same
way for both and send a "you already have an account" email instead.

**The register page hides the password rules until a password breaks one.**
The user chose a shorter first view of the form (2026-10-15). WCAG 3.3.2 is
still met: the field is labelled, the first failed submit names the broken
rule, and from then on the full rule list shows beside it as the field's
hint (`RegisterPage.jsx`). The cost is one failed submit for a user who
guesses wrong. Spaces and emoji are left out of the list; their own messages
explain them when they come up. *Revisit when:* email verification is added,
which reworks registration anyway.

**No refresh-token reuse detection.** A replayed, already rotated refresh token
gets 401 `AUTH_TOKEN_REVOKED`, but does not revoke the rest of that user's
sessions. Revoking on reuse would also log out a second tab that lost the
rotation race. *Revisit when:* the app holds data that justifies logging users
out on a false positive.

**No per-IP quota on the whole API.** Only login, register, refresh and
account deletion have Flask limits; users sharing an address (offices, carrier NAT) would lock each
other out. nginx's per-IP `limit_req`/`limit_conn` on `/api` is the coarse
backstop.

**Rate limits fall back to per-worker memory while Redis is down.** Limits get
looser (per worker, reset on restart) instead of every limited route failing.

**A Redis outage still costs a few seconds once per reconnect window.** While
Redis is down, `RedisService`'s circuit breaker fails calls at once, but every
`RECONNECT_INTERVAL_SECONDS` (5 s) each worker lets one call probe Redis. The
probe pays the 1 s lookup of the stopped container's name twice (the client's
one retry, kept so a connection Redis dropped is replaced unseen), and login
adds Flask-Limiter's own 1 s probe. Measured (PR #28, backend on
`APP_ENV=production`): login 503 in about 4 s at worst, refresh 3 s, other
routes 1 s, everything else in the window under 100 ms. The answer is the
same 503 either way. A no-retry probe client would save about 1 s for a
second client and more breaker code. *Revisit when:* a readiness check or
alert exists for Redis, or users see these delays outside an outage.

**Flask rate limits are off in E2E.** E2E registers dozens of accounts from
one address, which register's `10 per hour` would block, so the E2E backend
runs `IntegrationConfig` with limits off. The keying on the client IP
(`TRUSTED_PROXY_COUNT` and nginx's `X-Forwarded-For`) is unit-tested with
hand-made headers, and the Redis counters are integration-tested. CI's
Platform smoke job runs the real load balancer → nginx → Flask path, in
`behind-proxy` mode with the production config, and checks the address the
backend logs; `tls` mode's path runs only in production. *Revisit when:* a
deployment exists, or the proxy chain changes (a CDN hop, a second proxy).

**User text stored verbatim.** No server-side sanitizing; output escaping is
the render layer's job (React escapes text). Sanitizing on input corrupts data
and still misses other output contexts.

**No CORS.** The browser only calls a relative `/api`, same-origin in every
environment. Adding CORS would only widen what can call the API.

**gixy-ng skips `hsts_header` and `try_files_is_evil_too`.** HSTS is
meaningless on the port-80 redirect server (RFC 6797 8.1) and is asserted
over HTTPS by `e2e/nginx.spec.js`; the `try_files` warning is a performance
opinion that doesn't matter for a few static files. See the `nginx` job in
`.github/workflows/ci.yml`.

**Dev keeps a debug toggle.** `.env.dev` turns Flask debug on; `FLASK_DEBUG=0
./run_dev.sh` turns it off for one run. Production forces it off in
`ProductionConfig`.

**Access tokens outlive logout by up to 15 minutes.** Logout and "Log out all
devices" revoke refresh tokens only; an access token already issued works
until it expires. Revoking those too would put a Redis lookup on every API
request and make every request depend on Redis.
*Revisit when:* the app holds data where a 15-minute window after logout
matters.

**No nginx healthcheck.** Compose uses healthchecks only to order startup and
never restarts an unhealthy container, and nothing depends on nginx, so a
healthcheck would do nothing. *Revisit when:* a monitor or orchestrator acts
on container health.

**Unreachable CVEs in base-image OS packages are low.** A scanner flagging an
Alpine library in the nginx or backend image (e.g. libexpat or libtiff in
`nginx:*-alpine`) is a finding only if this configuration can reach it:
a loaded module uses it, or visitor input reaches it. Unreachable ones are
fixed by the upstream image's regular rebuilds, picked up with
`docker compose build --pull`, not by `apk upgrade` in the Dockerfile, which
makes builds unrepeatable and fails hadolint (DL3017). The libraries the
stack does use (OpenSSL, musl, zlib, and pcre2, which nginx's log maps and
`location` regexes run on every request) are judged per CVE: a bug in
compiling a pattern only reaches the patterns in the config, while a bug in
matching one reaches visitor input. *Revisit when:* an nginx module that
uses one is enabled (XSLT, image filter), or the CVE is reachable in a
library the stack uses.

**Unreachable CVEs in the `db` and `redis` images are low too.** The same
rule covers them. In the MySQL image, the gosu binary (its Go stdlib), the
bundled MySQL Shell's Python packages, and DTLS-only OpenSSL CVEs are
unreachable: gosu runs once at start with no network, mysqlsh is never run,
and MySQL speaks TLS over TCP only. They are fixed by bumping the pinned tag
once upstream ships one. *Revisit when:* the CVE is in the server's TLS or
authentication path, or the compose file starts running mysqlsh.

**The backend image ships `ordered-set` without its license file.** It is
MIT (a Flask-Limiter dependency), and its wheel has no license file in
`.dist-info`, unlike every other installed package. MIT's notice condition
applies to copies handed to others, and the backend image only runs on the
operator's own server. The frontend's notices do ship
(`third-party-licenses.txt`), since every visitor receives the bundle.
*Revisit when:* images are pushed anywhere others can pull them, or shipped
to anyone else to run.

**Images are run, not distributed.** The MySQL image, and the Debian and
Alpine userlands under the backend and nginx images, contain GPL and LGPL
code. Running them on the operator's own servers creates no duty; only
handing the built images to someone else would bring source-offer duties.
`deploy.sh` builds them on the server and pushes them nowhere; pushing them
to a private registry for one's own deploys (a platform's, such as ECR) is
not distribution either. *Revisit when:* images are pushed anywhere others
can pull them, or shipped to anyone else to run.

**Redis 8 is used unmodified under its tri-license.** Redis 8 is licensed
under RSALv2, SSPLv1 or AGPLv3, at the user's choice. The stack runs the
`redis:8.10-alpine` image unmodified as a private store that users never
reach, which none of the three restricts. *Revisit when:* Redis is modified or offered to
customers as a service, or a lawyer prefers Valkey (BSD-3-Clause).

**The template's copyright is its owner's.** The first commit came from a
university email address, but the template has always been the owner's
personal project, made outside any university employment, grant or course,
so `LICENSE` names the owner alone. *Revisit when:* the university raises a
claim.

**The template is MIT-0.** An app built from the template keeps much of its
code, so under MIT every derived app would have to carry the template's
notice. MIT-0 drops that condition, so README's step 6 can tell a new app to
replace `LICENSE` outright (LEGAL-19). *Revisit when:* the owner wants
attribution from derived apps.

**Legal placeholders are not enforced at build.** Nothing stops a
production image from serving the placeholder `OPERATOR` values in
`frontend/src/legal.js`, `contact@example.com` in `security.txt`, or the
"Placeholder" banner on the legal pages. `docs/personal-data.md`'s "Before launch" list is
the only safeguard: a build check would have to tell the production image
apart from the test stack's, which serves the same placeholders on purpose
(LEGAL-21). *Revisit when:* the first real deployment is prepared.

**Password composition rules and no spaces.** Every password the app
accepts (register, login, account deletion) must hold upper and lower case
and a digit, and no spaces. That gives up ASVS 6.2.5 ("passwords of any
composition") and NIST's advice to allow spaces, in exchange for the current,
simpler rule set (the user's choice). Login and account deletion apply the
same rules as registration, so no password registration refuses is ever
checked; nothing was deployed, so no account predates them. *Revisit when:* a
common or breached-password check is added, which makes composition rules
redundant; loosen a rule everywhere at once, since the schemas share one
`Password` type.

**scrypt at Werkzeug's default cost.** Password hashes use `scrypt:32768:8:1`
(N=2^15), below OWASP's N=2^17. Raising it costs about 4× the CPU and memory
per hash (~128 MB), which has to be sized against the real server's CPU,
memory limit and `PASSWORD_HASH_CONCURRENCY`. *Revisit when:* the app runs on
its production hardware.

**A distributed lockout is still possible, for an hour at a time.** Login is
limited per account and IP (5 failures a minute), so one attacker locks out
only their own address, but the per-account cap (100 failures an hour, from
any address) can still be filled by a botnet, keeping the owner out until
the hour passes. The cap is what bounds distributed password guessing, so it
stays. *Revisit when:* users report lockouts, or the app holds accounts worth
targeting (then add a CAPTCHA or an emailed unlock link instead of the hard
cap).

**No mutation-testing tool.** New tests are mutation-checked by hand (CLAUDE.md
Test Architecture). *Revisit when:* the suites grow past what spot checks can
cover; mutmut and Stryker are the candidates (SOURCES.md, Testing).

**`ConfirmDialog` keeps the native `<dialog>` defaults.** A click on the
backdrop does not close it (only Cancel, Escape or the confirm button do),
and Tab from its last button passes through the browser's own toolbar before
wrapping back into it. Both are how `showModal()` behaves in every browser;
overriding them means hand-written focus trapping and click handling, which
CLAUDE.md's prefer-the-built-in rule argues against.

**A pasted note is cut to its limit without a message.** The note input uses
the native `maxLength`, so pasting more than 256 characters keeps the first
256; the live counter then reads "0 characters remaining", which is the only
sign. Showing an
over-limit error instead means dropping `maxLength` and checking on submit,
for every limited field. Chosen while planning PR #25. *Revisit when:* users
report losing pasted text, or a field's limit is one people often reach.

**`/api/health` is liveness only.** It answers 200 while MySQL or Redis is
down; the routes that need them answer 503 instead. Compose orders startup
on it, `deploy.sh` rolls back when it fails through nginx, and a platform's
load balancer routes on it. A readiness check would add little to any of
them: the backend does not start serving until `wait_for_services.py` has
reached MySQL and Redis and checked its grants, and a load balancer that
drops every task during a database outage turns 503s into 502s. *Revisit
when:* a deploy needs to catch a commit that starts but cannot serve (then
a smoke request after the health check, in `deploy.sh`), or a platform must
stop routing to a task that lost its database.

**`email-validator` is called directly, not through Pydantic's
`EmailStr`.** `EmailStr` accepts a display name (`Name <a@b.c>`), allows
SMTPUTF8 local parts, and returns the Unicode `normalized` form.
`normalize_email` needs `allow_smtputf8=False` and the `ascii_email` form,
which keeps one mailbox per account and is the login limit's key.
*Revisit when:* Pydantic's email type gains those options.

**No `engines` field, the `react-router-dom` shim, unhashed Python locks.**
CI and Docker pin one Node major (`check_versions.py`), the shim costs
nothing at runtime, and Dependabot plus exact pins cover the locks.
*Revisit when:* a contributor hits a Node mismatch, React Router drops the
shim, or a supply-chain incident touches PyPI.

**A write the client was told failed may still have committed.** When a
commit stalls inside MySQL (a hung server), the query timeout or
nginx's 60s gives up and the client gets a 503 or 504, but MySQL can finish
the commit later. Retrying then repeats the write: a duplicate note, or a 409
for an account that was in fact created. This is the general ambiguous-failure
problem, and plain CRUD creates take it. Where a duplicate does harm
(payments, orders, sent messages), use an idempotency key: the client sends
an `Idempotency-Key` per submit and reuses it on retry; the table stores it
with a unique index on (owner, key), written in the same transaction as the
row; a repeat returns the existing row. A key kept only in Redis would not
catch this case. *Revisit when:* a feature's writes must never repeat.

The same goes for a refresh. If the backend stalls past nginx's 60s during
`/auth/refresh`, the client gets a 504, but the backend can still finish the
rotation: the old token is revoked and the new cookie goes out in a response
no one receives. The client's next refresh then gets 401
`AUTH_TOKEN_REVOKED`, and that device is signed out. It takes a stall of over
a minute landing on a refresh, and the cost is one login. Accepting the
previous token for a grace window after rotation would avoid it, but it
weakens one-time rotation (a stolen token could be replayed inside the
window) and complicates the Lua script. *Revisit when:* users report
sign-outs after slow responses, or refresh moves behind a shorter timeout.

Account deletion is the third case. It revokes every session before it
deletes the `users` row, so a delete that stalls in MySQL and answers 503
has already signed the user out everywhere, and MySQL may still commit the
delete afterwards: the user logs in again to find the account gone, or still
there if MySQL never committed it. Either way nothing is half deleted, since
the row and its cascade go in one statement. The recovery audit drilled it
(2026-10-16). *Revisit when:* deletion gains a step outside that statement
(files in object storage, a third-party account), which then needs to run
only after the commit.

**The requirements check stays a test, not deptry.**
`tests/unit/test_requirements.py` checks that `requirements.in` lists every
package the backend imports. deptry (0.25.1) would do the same and also
find listed packages nothing imports, but it needs a `pyproject.toml`
section the backend doesn't otherwise have. *Revisit when:* an unused
package slips into `requirements.in`, or the backend gets a
`pyproject.toml`.

**Python import contracts stay a custom test, not import-linter.**
`tests/unit/test_import_rules.py` does what import-linter's `layers` (with
`exhaustive = true`) and `protected` contracts do, and finds new features by
itself. import-linter (tried, version 2.15) skips packages without an
`__init__.py`, so adopting it means five empty `__init__.py` files, a
scaffold step to list each feature in the contract, and five dev packages
(about 10 MB). *Revisit when:* the feature packages get `__init__.py` for
another reason, or the rules outgrow the test (more layers, per-feature
exceptions).

**Frontend folder rules stay a custom ESLint rule, not
`eslint-plugin-boundaries`.** `eslint.config.js`'s `relative-within-folder`
rule (about 25 lines) and the `@/` patterns enforce the one-way imports, and
`src/__tests__/eslintRules.test.js` plants violations of each. `boundaries`
would declare the same rules more declaratively, but it resolves paths
through `eslint-plugin-import`'s resolvers, so the `@/` alias needs two or
three more dev packages, and the planted tests would stay anyway, since
config fails silently. *Revisit when:* the rules outgrow the custom rule
(more layers, per-feature exceptions), as for import-linter above.

**Ruff's `select` lists every rule in full.** Ruff's own default set (checked on
0.16) is far wider than pyflakes and syntax errors (`I`, `SIM`, `B`, `RUF`,
`UP` and about 30 more families), and it changes between releases, so
`extend-select` would turn on whatever the installed ruff defaults to.
*Revisit when:* the repo chooses to adopt ruff's defaults.

**axios stays.** The api client relies on what axios provides: request and
response interceptors, `error.config` for retrying the original request,
JSON and non-2xx handling, and the `err.response.{status,data}` shape that
`getErrorMessage`, `AccountPage` and 8 test files read. A `fetch` wrapper
would hand-write all of it. It costs 23 KB gzipped in the bundle; its 27
lockfile packages (all MIT) are mostly Node-only and not bundled. *Revisit
when:* the client needs streaming or `AbortSignal` beyond what axios offers,
or a major axios release changes the interceptor API.

**Pages load data in effects, not React Router loaders.** `AccountPage` and
`useNotes` fetch in `useEffect`, while the app already uses
`createBrowserRouter`. A loader would fire before `ProtectedRoute` renders,
so a signed-out visit would send an unauthenticated request and land on the
`errorElement` instead of `/login`. Using loaders means moving both guards
into loaders (`throw redirect(...)`) and rebuilding the "Loading..." live
regions on `useNavigation`. *Revisit when:* together with TanStack Query
(below), or when a page needs data before first paint.

**pytest-cov stays.** `coverage run -m pytest` plus `coverage report` could
replace it, but that saves one small dev package in exchange for rewriting
`run_tests.sh`'s `--cov`/`--cov-append`/`--cov-fail-under` flags. *Revisit
when:* pytest-cov lags a pytest major release.

**The JSON log formatter stays hand-written.** `app/utils/log.py`'s
`JsonFormatter` is a few lines. `python-json-logger`, the usual library for
this, would replace it with a dependency and its configuration and save
nothing the app needs today. *Revisit when:* a log service needs a specific
schema (Elastic ECS, Datadog's reserved fields), every line needs tracing ids
(OpenTelemetry), or the formatter grows past about 40 lines.

**The color guard stays a Vitest test, not stylelint.**
`styles/__tests__/stylesheets.test.js` refuses a color written outside
`tokens.css`, and a token that is unused or never defined. stylelint covers
only the first half (`color-named`, `color-no-hex`,
`function-disallowed-list`), and would add a CLI, a config and a CI step.
*Revisit when:* the CSS needs rules a stylelint preset already has
(ordering, specificity, property bans), or the hand-written check misses a
case.

**Keeping and shipping logs belongs to the platform.** The app and nginx log
to stdout, so any platform can take the lines: a managed platform's log
service (CloudWatch, Cloud Logging) ships each line off the host as it is
written and keeps it for a set period. The template builds no log shipping of
its own, which would tie it to the self-hosted Docker path. On the bundled
Compose deployment, Docker's 3 × 10 MB per container is all there is: it caps
by size, not age, and enough traffic can push older lines out. It also goes
with its container, and every deploy replaces the backend and nginx, so the
logs reach back to the last deploy at most. nginx cuts the
client's text in each access line short, rate-limits the page as well as the
API per address, and logs only a sample of what it refuses (below), which
makes that slow for one client but not impossible for many. Measured on
2026-10-18: one client sending ~4200 requests a second with 4 KB headers
wrote 51 KB for 4000 requests, where it wrote 11.2 MB (an access line and an
error-log line per refusal) before the sampling. Its served lines and the
sampled refusals, about 770 bytes each, roll 30 MB over in about 13 minutes
on one zone, and (by the same numbers) about 8 if it floods the page and the API together.
Keeping logs past a deploy, or shipping them, is generic server operations
(below): any Compose app that replaces its containers needs the same
logging driver or agent, so "Not Included" names them (journald in an
untracked `docker-compose.override.yml`, Loki, Fluent Bit, CloudWatch)
rather than the template building one (user, 2026-11-05). What the docs
cover is why it matters here: every deploy erases the backend's and nginx's
logs, and their `account_deleted` events are the only record of which
accounts a restore brings back. *Revisit when:* keeping those events past
a deploy comes to need something only this template can provide.

**nginx logs a 1-in-100 sample of refused requests.** A client over a rate
limit gets its 429, and nginx writes an access line for one refusal in 100,
picked by `request_id` (`split_clients` in `nginx.conf`); refusals leave the
error log entirely (`limit_req_log_level info`). Logging every refusal let one
client roll Docker's 30 MB over in about 4 seconds, erasing everything older,
the flood's own start and other users' requests included; the error-log
lines also kept the whole query string and Referer, which the access log
cuts at the query.
Logging none was rejected too: nginx's 429s never reach Flask, so no
`rate_limited` event would show that a flood happened or where it came from.
The sample keeps the flood's address, timing and paths (multiply by 100 for
its size). The cost: exact counts are lost, and a single 429 a real user got
is likely not logged. `nginx.spec.js` checks both halves. *Revisit when:* logs
are shipped off the host (then log every refusal).

**One backend container, at a fixed address.** nginx connects to the
backend's fixed address on the edge network, not to its name, so a recreated
backend is reached the moment it listens: looked up by name, Docker's DNS
could answer "server failure" mid-swap, and nginx then left a healthy backend
unreachable for about 30s. Two containers cannot share the address, so
`--scale backend=N` is out; scale one container with `WEB_CONCURRENCY` and
its CPU limit instead. A managed platform's load balancer does this job there.
*Revisit when:* one backend container is no longer enough (then several
fixed addresses in the upstream, or a reload of nginx after every deploy).

**A deploy is not zero-downtime.** With one backend, `deploy.sh` stops the old
one before the new one starts: the old nginx keeps serving the page, but the
API answers a JSON 502 or 504 until the new backend listens (measured on a
4 GB VM: 8.5 s), and connections are refused for about a second while nginx
itself is replaced. A commit that changes the bundled `db` or `redis` (its
image, command or values) restarts it under the running app, which answers
503 meanwhile. *Revisit when:* a deploy's API gap matters to users (then
two backends, as above, started one after the other).

**nginx's per-IP limits are per nginx.** On a platform, each task runs its
own nginx beside its backend, so three tasks give one client three times the
budget of `limit_req`/`limit_conn`. The backend's own limits (login,
register, refresh, account deletion) count in Redis and stay exact. Exact
limits at the edge belong to the load balancer's WAF. *Revisit when:* a
deployment runs enough tasks that the multiplied budget matters.

**No IPv6 at the edge.** nginx publishes 80 and 443 on IPv4 only
(`0.0.0.0`, `check_compose.py`), so an IPv6 visitor is refused and the
browser falls back to IPv4; a server publishes no AAAA record. Published on
`[::]` as well, Docker's proxy would relay every IPv6 visitor from the
`edge` gateway's address (seen on the test VM, 2026-11-05), giving them all
one rate-limit bucket that a stranger's wrong passwords could lock. Real
IPv6 needs IPv6 on `edge`, which a host with IPv6 switched off cannot
create, and per-address limits keyed on the visitor's /64, since most hold
a whole /64 and could rotate through it. Behind a dual-stack load balancer
(`behind-proxy`) IPv6 visitors already arrive with their own address in
`X-Forwarded-For`, so there the limits key on a single IPv6 address today:
the per-account login limits hold, the per-address ones can be dodged.
*Revisit when:* a deployment needs IPv6 at nginx, or runs behind a
dual-stack load balancer (then the /64 keying, in nginx and in Flask).

**`--provenance=false` stays a flag.** Without it, every rebuild gets a new
image ID and a hand-run `up -d` replaces the app containers though nothing
changed. On Docker Engine 29 with Compose 5.6.1 (the test VM, 2026-11-05)
the flag keeps an unchanged image's ID, and so does `provenance: false`
under `build:`. But that key is honored only since Compose 5.5.1
(docker/compose#14112): 5.0 ignores it, and some versions in use refuse the
whole file over it (GitHub's `ubuntu-24.04` runner, 2026-11-06: "additional
properties 'provenance' not allowed"), which would stop the stack and
`deploy.sh` from starting at all. The flag is accepted everywhere it exists.
*Revisit when:* every Compose a deployment could run, CI's runner included,
accepts and honors the key.

**Deploys build on the server, not in CI.** `deploy.sh` builds the
commit it deploys on the server itself, so the images that run are a second
build of the tree CI tested, not the images it tested: branch protection ran
every check on that same tree, and the lockfiles pin what the build
installs. A registry fed by CI would mean either public images (GitHub makes
a public repository's packages public: distribution, see "Images are run,
not distributed") or a manual, per-package setup and a registry login on
every server. The cost is building on the server (internet access, memory
for the frontend build, a few minutes per deploy while the old version
serves). The build pulls its base images (`build --pull`), so a base
image's security patch reaches the server with the next deployed commit;
nothing rebuilds on a schedule, and a rollback, or a redeploy of a commit
whose images are still there, reuses its images. *Revisit when:* an image must be byte for
byte the one tested, servers are too small to build, a base-image fix has to
ship with no commit to carry it, or deploys move to a platform that pulls
from a registry.

**The bundled MySQL and Redis images change only with a tag bump.**
`deploy.sh` doesn't pull `db`'s and `redis`'s images: upstream rebuilds of a
pinned tag are not taken, so they are recreated only by a commit that
changes their tag (Dependabot's `docker-compose` entry) or their settings.
Pulling would restart MySQL or Redis under the running app whenever
upstream rebuilt the tag, and most real deployments replace both with
managed services, whose providers patch them. *Revisit when:* a reachable
CVE in either is fixed by a same-tag rebuild.

**Deploys trust GitHub's `main`.** `deploy.sh` deploys any commit on
`origin/main`, and `--latest` on a timer does so unattended, so whoever can
push or merge to `main` (a stolen GitHub session or token included) runs
code on the server as the deploy user, who can control the host through
Docker. Branch protection and its required checks are the only gate. A
signature check on the server would only help with commits signed by a key
GitHub never holds: merges made in GitHub's UI, Dependabot's included, are
signed by GitHub's own key, which a stolen session uses too, so every merge
would have to be made and signed locally. *Revisit when:* the timer runs on
a host with real data (then signed merges and `git verify-commit` against an
`allowed_signers` file on the server, or a deploy that waits for a person's
approval).

**Generic server operations are out of scope.** The template documents what
depends on how it is built (restarts, its MySQL volume's dump and restore,
what its init script and secrets do on rotation, `deploy.sh`), and leaves
what any Docker host needs to the tools made for it: alerts and uptime
checks, host metrics, log shipping, scheduled and off-host backups,
point-in-time recovery (a managed database), host hardening and its audits
(Lynis, Docker Bench, CIS). `docs/deployment.md`, "Operating in
Production", says what is not included and which tool to reach for; audits
report a missing one only where those docs fail to name it. *Revisit when:*
a gap's answer comes to depend on how this template is built.

**Encryption at rest is the host's job.** The MySQL volume, Redis's files
and backups are protected by encrypting the disk they sit on: full-disk
encryption (LUKS or the OS's equivalent) on a self-hosted server, the
provider's default encryption on a cloud disk or managed database, and
backups encrypted before they leave the host. The app encrypts no columns:
its key would sit in the same environment as the database URL, so it would
only guard against a stolen disk or backup, which disk and backup
encryption already cover. The cost on a self-hosted server is that every
boot waits for the passphrase (or a TPM or network unlock), so an
unattended reboot leaves the app down until someone unlocks the disk.
*Revisit when:* a field must stay unreadable to whoever runs the database,
such as under a compliance rule (then column encryption with a key held
outside the app's environment).

**MySQL only.** The template runs on MySQL 8.4, bundled or managed. Another
engine would be a project of its own: the driver and its connect args (query
timeouts, the UTC session time zone), the migrations, the MySQL-only
integration tests, and case-insensitive email matching, which MySQL's
collation gives for free and Postgres would need `citext` or a lower-cased
unique index for. *Revisit when:* a deployment needs a provider or host
without MySQL.

**No TLS between containers on one host.** It is not needed while every
service shares one host: the bundled MySQL and Redis traffic stays on the
`internal` network, and anyone who can sniff that bridge already has root
on the host. Off-host (any host but `db` or `redis`), `ProductionConfig`
requires it. *Revisit when:* the bundled services are spread across hosts,
since an overlay network keeps the names `db` and `redis`, so
`ProductionConfig` would not ask for TLS.

## Deferred until the app grows

**TanStack Query.** It would replace the hand-written loading, error and
pagination code in `useNotes` and `useHealth`, but it costs a dependency and a
provider, needs retry and refetch-on-focus defaults turned off, and must be
cleared on logout. *Revisit when:* there are several server lists, or data
shared across pages.

**React 19 form actions (`<form action>`, `useActionState`).** In a
client-only SPA React resets the form after every submit (a failed login would
wipe the email), and live error clearing and the note character counter need
controlled inputs anyway. The real gains need server rendering. *Revisit
when:* the app adopts a server-rendering framework.

## Known gaps (open work, not new findings)

A check mentions these only when its findings bear on one (for example, a
docs check that finds the certificate steps wrong). They are not new
findings.

- **Email verification**; **data export** (GDPR Art. 15, 20) and **email
  change** (Art. 16), which the privacy notice handles by email meanwhile.
- **Account security beyond the basics:** no password change, password
  reset, multi-factor login, or common/breached-password check (ASVS 5.0
  chapter 6, Authentication). Reset and change wait on email verification.
  No list of active sessions either (ASVS 7.5.2): a user can end every
  session with "Log out all devices" but cannot see them. It belongs on
  `AccountPage`.
- **Certificate renewal waits for the work on the test server.** The Let's
  Encrypt steps still edit the tracked `docker-compose.yml` and the shared
  nginx template (which breaks CI and the test stack if followed, and leaves
  a `deploy.sh` clone dirty), and renewal is manual. It gets written and
  tried on that server rather than on paper; until then the docs and
  recovery checks don't report it. A CDN is not set up either.
