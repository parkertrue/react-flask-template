# Audit decisions

Choices an audit would otherwise flag, recorded so every run stops re-raising
them. Each entry says what was chosen and why. A check reports an entry here
only if its **Revisit when** condition has come true, or the code no longer
matches the entry (then the entry is stale and that is the finding).

Add an entry when a finding is deliberately kept as-is, under the heading it
fits. Delete one when the code changes so it no longer applies. Open work
belongs in `OPEN-ISSUES.md`, not here.

In a *Revisit when*, "a deployment", "a real server" and "production" mean
one that serves real users and holds their data. A server the maintainer runs
for testing doesn't count, even one that deploys every merge to `main`.

## Auth and accounts

**Access token in localStorage.** The 15-minute access token is readable by
any XSS; the refresh token stays in an HttpOnly cookie. Mitigated by the short
expiry, the CSP, and React's escaping. Keeps the client simple: no cookie for
API calls, so no CSRF on them. See the comment in `frontend/src/auth/storage.ts`.
*Revisit when:* the app renders third-party or user-supplied HTML.

**One set of password rules, at login too** (user, 2026-11-09). Every
password the app accepts (sign-up, login, a reset, account deletion, an
email change, a password change) is one `Password` type: 15 to 128
characters, NIST's minimum for a password that is the only factor, with no
composition rules. Login applies the length too. *Revisit when:* the rules
tighten on a deployment with real users, which then needs login to accept
the old ones while a password change replaces them.

**scrypt at Werkzeug's default cost.** Password hashes use `scrypt:32768:8:1`
(N=2^15), below OWASP's N=2^17. Raising it costs about 4× the CPU and memory
per hash (~128 MB), which has to be sized against the real server's CPU,
memory limit and `PASSWORD_HASH_CONCURRENCY` (`OPEN-ISSUES.md`, Production
to-dos). *Revisit when:* the app runs on its production hardware.

**A breached-password check that fails open** (user, 2026-11-09). Sign-up, a
password reset and a password change check a new password against Pwned
Passwords' range API (`backend/app/utils/breached.py`), as NIST SP 800-63B
requires: 5 characters of its SHA-1 leave the server, padded. If the service
is down or slow (2 s for the whole call, on a pool of 4 threads, so it holds
no request thread or database connection), the password is accepted and
`breach_check_failed` logged, since a third party's outage must not stop
sign-up. Login, account deletion and an email change only compare, so never
check. CodeQL's `py/weak-sensitive-data-hashing` alerts on that SHA-1 (in
`breached.py` and its test) were dismissed as false positives: SHA-1 is how
the API names a password, the full hash never leaves memory, and stored
passwords stay scrypt. *Revisit when:* the service's outages show up often in
the log, or the app holds data that justifies refusing sign-up while it is down.

**No refresh-token reuse detection.** A replayed, already rotated refresh token
gets 401 `AUTH_TOKEN_REVOKED`, but does not revoke the rest of that user's
sessions. Revoking on reuse would also log out a second tab that lost the
rotation race. *Revisit when:* the app holds data that justifies logging users
out on a false positive.

**Sign-up proves the address first, and answers every address alike**
(user, 2026-11-09). `POST /api/auth/register` takes an email alone, answers
202 whatever the address, and queues either a link to finish (24 hours) or,
for a registered address, a note saying so. No row exists until the link is
used, so the form never tells a stranger which addresses have accounts, and a
mistyped address leaves nothing behind. Each link works once, even after the
account it made is deleted (its hash is kept in Redis for its lifetime). The
costs: two steps, and nobody can sign up while email or Redis is down or
email is unconfigured (a local production run included). *Revisit when:* an
app needs accounts without a verified email (an invitation flow, SSO), or the
24-hour window proves too short or too long.

**A logout ends access at the device's next request, except while Redis is
down** (user, 2026-11-19). Every access token names its session (`sid`), and
the user loader checks in Redis (one ZSCORE per signed-in request) that it is
still live, so logging out, ending a device from the account page, and "Log
out all devices" all take effect at that device's next request (ASVS 5.0
chapter 7). A password change or reset refuses older tokens through
`password_state`, with no Redis at all. While Redis is unreachable the
session check is skipped (fail open), so signed-in pages keep working;
refresh and login still fail closed, so a session ended during an outage
lasts at most its 15-minute access token. Refusing every signed-in request
while Redis is down was weighed and dropped: it turns a Redis outage into an
outage of the whole signed-in app. *Revisit when:* a session ended during a
Redis outage must stop at once, or the per-request lookup shows in
`upstream_response_time`.

**A distributed lockout is still possible, for an hour at a time.** Login is
limited per account and IP (5 failures a minute), so one attacker locks out
only their own address, but the per-account cap (100 failures an hour, from
any address) can still be filled by a botnet, keeping the owner out until
the hour passes. The cap is what bounds distributed password guessing, so it
stays. Recovery has the same weakness, for a day: a password reset's own
per-address budget (3 an hour, 6 a day, from any address) bounds the mail one
inbox can be sent, so a stranger who spends it leaves the owner's reset at
429 until the day's window ends (sign-up and email changes have a budget
of their own). *Revisit when:* users report lockouts, or the app holds accounts
worth targeting (then a CAPTCHA or an emailed unlock link instead of the hard
cap, and a CAPTCHA once an address's reset budget runs low).

**An undo link works for 7 days, whatever changed since** (user,
2026-11-20). After an email change, the old address gets a link that moves
the account back and ends every session. Its state names only the account
(id and creation time), so an intruder who changed both the address and the
password cannot outrun it. The cost: for those 7 days, whoever reads the old
inbox can take the account back, including a mailbox the owner left because
it was compromised, reclaimed by an employer or lost with a lapsed domain.
*Revisit when:* users report accounts taken back from an old address, or the
app holds data that justifies support-assisted recovery instead.

**A token in a link travels in the URL fragment, and the page posts it
after a click** (user, 2026-11-08). Every emailed link that carries a secret
is `https://<host>/<page>#token=...` (`app_link`, `backend/app/utils/links.py`).
Browsers send a fragment to no server and in no Referer. nginx's error log
writes the whole request line for a 413, 502 or 504, so a token in a query
string would land there whenever the backend restarts; lowering `error_log`
to `crit` was dropped, since it loses the upstream errors an outage is
diagnosed from. The page asks for one click before posting, since mail
scanners open links and some run their scripts; sign-up's page asks for the
password, which is that click. *Revisit when:* never for secrets; a link
that carries no secret may use a query string.

**The data export is one synchronous JSON response, with no password asked
for** (user, 2026-11-08). `GET /api/account/export` reads every registered
feature's rows in one request. Every feature caps a user's rows (the notes example: about
300 KB at most), which bounds the response; a background export would add
file storage, its cleanup and an emailed download link for no gain. A stolen
session can already read every row through the other routes, so a password
adds nothing. The logs are not in it: the privacy notice takes requests for
them by email. *Revisit when:* a feature's per-user data can outgrow one
response (file uploads, a long history), or the export holds anything the
other routes never show (then ask for the password).

**`email-validator` is called directly, not through Pydantic's
`EmailStr`.** `EmailStr` accepts a display name (`Name <a@b.c>`), allows
SMTPUTF8 local parts, and returns the Unicode form. `normalize_email` needs
`allow_smtputf8=False` and the `ascii_email` form, which keeps one mailbox
per account and is the login limit's key. *Revisit when:* Pydantic's email
type gains those options.

## Rate limits

**No per-IP quota on the whole API.** Only the auth and account routes CLAUDE.md
lists under `auth/` have Flask limits; users sharing an address (offices,
carrier NAT) would lock each other out. nginx's per-IP `limit_req`/`limit_conn`
on `/api` is the coarse backstop.

**Rate limits fall back to per-worker memory while Redis is down.** Limits get
looser (per worker, reset on restart) instead of every limited route failing.

**Flask rate limits are off in E2E.** E2E registers dozens of accounts from
one address, so the E2E backend runs `IntegrationConfig` with limits off. The
keying on the client IP is unit-tested with hand-made headers, the Redis
counters are integration-tested, and CI's Platform smoke job runs the
load balancer → nginx → Flask path in `behind-proxy` mode with the production
config; `tls` mode's path runs only in production. *Revisit when:* a
deployment exists, or the proxy chain changes (a CDN hop, a second proxy).

**nginx's per-IP limits are per nginx.** On a platform, each task runs its
own nginx, so three tasks give one client three times the `limit_req`/
`limit_conn` budget. The backend's own limits count in Redis and stay exact;
exact limits at the edge belong to the load balancer's WAF. *Revisit when:* a
deployment runs enough tasks that the multiplied budget matters.

**nginx logs a 1-in-100 sample of refused requests.** A client over a rate
limit gets its 429, and nginx writes an access line for one refusal in 100,
picked by `request_id`; refusals leave the error log entirely
(`limit_req_log_level info`). Logging every refusal let one client roll
Docker's 30 MB over in about 4 seconds. Logging none was rejected too: nginx's
429s never reach Flask, so nothing would show that a flood happened or where
from. The cost: exact counts are lost, and a single 429 a real user got is
likely not logged. `nginx.spec.ts` checks both halves. *Revisit when:* logs
are shipped off the host (then log every refusal).

## Outages and failures

**A Redis outage still costs a few seconds once per reconnect window.** Every
call a request makes to Redis (the token store, the job queue, and the
session check on every signed-in request) shares one breaker per worker
process (`redis_unreachable`): once a call fails to connect, each fails at
once for `RECONNECT_INTERVAL_SECONDS` (5 s), then one call probes again. The
probe pays the 1 s lookup of the stopped container's name twice (the
client's one retry, kept so a connection Redis dropped is replaced unseen),
and a rate-limited route adds Flask-Limiter's own probe. Measured: a login on
the probe answers 503 in about 4 s at worst, a signed-in request 200 in up to 3 s;
the rest of the window is as fast as with Redis up. A no-retry probe client
would save about 1 s for more breaker code. *Revisit when:* a readiness check
or alert exists for Redis, or users see these delays outside an outage.

**`/api/health` is liveness only.** It answers 200 while MySQL or Redis is
down; the routes that need them answer 503 instead. The backend does not
start serving until `wait_for_services.py` has reached MySQL and Redis and
checked its grants, and a load balancer that drops every task during a
database outage turns 503s into 502s. *Revisit when:* a deploy needs to catch
a commit that starts but cannot serve (then a smoke request after the health
check, in `deploy.sh`), or a platform must stop routing to a task that lost
its database.

**A write the client was told failed may still have committed.** When a
commit stalls inside MySQL, the query timeout or nginx's 60s gives up and the
client gets a 503 or 504, but MySQL can finish the commit later, so a retry
repeats the write (a duplicate note, or a 409 for an account that was in fact
created). Plain CRUD takes this. Where a duplicate does harm (payments,
orders, sent messages), use an idempotency key stored with the row under a
unique (owner, key) index in the same transaction; a key kept only in Redis
would not catch this case. Two more cases:
- *A refresh.* A stall past 60s during `/auth/refresh` can rotate the token
  in a response no one receives, and the device is signed out at its next
  refresh. A grace window for the previous token would weaken one-time
  rotation.
- *Account deletion* revokes every session before it deletes the `users` row,
  so a stalled delete has already signed the user out, and the account may or
  may not be gone; nothing is half deleted, since the row and its cascade go
  in one statement.

*Revisit when:* a feature's writes must never repeat, users report sign-outs
after slow responses or refresh moves behind a shorter timeout, or deletion
gains a step outside that statement (files in object storage, a third-party
account), which must then run only after the commit.

## Data stores

**MySQL only.** The template runs on MySQL 8.4, bundled or managed. Another
engine would be a project of its own: the driver and its connect args, the
migrations, the MySQL-only integration tests, and case-insensitive email
matching, which MySQL's collation gives for free. *Revisit when:* a
deployment needs a provider or host without MySQL.

**External services: one database user is not enough, and the bundled
services are known by name.** In production the backend refuses to start
when `DATABASE_URL`'s user holds more than row rights, with no opt-out, so a
provider that offers a single database user is unsupported (user,
2026-10-21). TLS is required for any host but `db` and `redis`, so renaming
those services means editing `config.py` too. One gap stays: a
`MIGRATION_DATABASE_URL` set on the backend itself wins over `DATABASE_URL`,
and the app then runs as the schema's owner; only the compose files'
`environment:` lists keep it on `migrate`. *Revisit when:* a deployment needs
a provider with one user, or the backend is run by something other than the
compose file.

**No TLS between containers on one host.** The bundled MySQL and Redis
traffic stays on the `internal` network, and anyone who can sniff that bridge
already has root on the host. Off-host (any host but `db` or `redis`),
`ProductionConfig` requires TLS. *Revisit when:* the bundled services are
spread across hosts, since an overlay network keeps the names `db` and
`redis`, so `ProductionConfig` would not ask for TLS.

**Encryption at rest is the host's job.** The MySQL volume, Redis's files
and backups are protected by encrypting the disk they sit on (LUKS or the
OS's equivalent, a cloud provider's default) and backups before they leave
the host. The app encrypts no columns: its key would sit in the same
environment as the database URL, guarding only against a stolen disk or
backup, which disk encryption already covers. *Revisit when:* a field must
stay unreadable to whoever runs the database (then column encryption with a
key held outside the app's environment).

**No production data in dev, scrubbed or not.** Scrubbed data that can still
be linked to a person is still personal data under GDPR, a developer's
machine is less protected than the server, note content is free text no
scrubber cleans reliably, and every new column of personal data would have
to join the scrubber's list. If dev needs volume or edge cases, generate them
(a dev-only seed command that refuses production); one user's bug is
reproduced on the server, with their consent. *Revisit when:* dev needs
something only real data shows.

## Deploy and infrastructure

**One backend container, at a fixed address.** nginx connects to the
backend's fixed address on the edge network, not its name, so a recreated
backend is reached the moment it listens; by name, Docker's DNS could fail
mid-swap and leave nginx without it for about 30s. Two containers cannot
share the address, so `--scale backend=N` is out; scale with
`WEB_CONCURRENCY` and the CPU limit. *Revisit when:* one backend container is
no longer enough (then several fixed addresses in the upstream, or a reload
of nginx after every deploy).

**A deploy is not zero-downtime.** `deploy.sh` stops the old backend before
the new one starts, so the API answers a JSON 502 or 504 until it listens
(8.5 s on a 4 GB VM), and connections are refused for about a second while
nginx is replaced. A commit that changes the bundled `db` or `redis`
restarts it under the running app, which answers 503 meanwhile. *Revisit
when:* a deploy's API gap matters to users (then two backends, started one
after the other).

**Deploys build on the server, not in CI.** The images that run are a second
build of the tree CI tested: branch protection ran every check on it, and the
lockfiles pin what the build installs. A registry fed by CI would mean public
images (distribution, see "Images are run, not distributed") or a per-package
setup and registry login on every server. The cost: servers need internet
access and memory for the frontend build, and a base image's fix arrives only
with the next deployed commit (`build --pull`); a rollback reuses its images.
*Revisit when:* an image must be byte for byte the one tested, servers are too
small to build, a base-image fix has to ship with no commit, or deploys move to
a platform that pulls from a registry.

**The bundled MySQL and Redis images change only with a tag bump.**
`deploy.sh` doesn't pull `db`'s and `redis`'s images, so an upstream rebuild
of a pinned tag never restarts them under the running app; a commit that
changes their tag (Dependabot) or settings does. Most real deployments use
managed services, which their providers patch. *Revisit when:* a reachable
CVE in either is fixed by a same-tag rebuild.

**Deploys trust GitHub's `main`.** `deploy.sh` deploys any commit on
`origin/main`, and `--latest` on a timer does so unattended, so whoever can
push or merge to `main` (a stolen GitHub session included) runs code on the
server as the deploy user. Branch protection is the only gate. A signature
check on the server would only help with commits signed by a key GitHub never
holds, so every merge would have to be made and signed locally. *Revisit
when:* the timer runs on a host with real data (then signed merges and
`git verify-commit` against an `allowed_signers` file, or a deploy that waits
for a person's approval).

**PRs need not be up to date with `main` to merge** (user, 2026-11-19).
Branch protection requires the status checks but leaves "Require branches to
be up to date before merging" off. On, every merge put every other open PR
behind, each needing a rebase and a ten-minute CI run. Git still refuses a
conflicting PR, and CI runs on `main` after every merge and nightly. The risk
accepted: two PRs that each pass alone can break together, and the deploy
timer can ship `main` before its CI reports; `deploy.sh` rolls back a release
that does not start. A merge queue is offered only to organisation-owned
repositories. *Revisit when:* several people merge in parallel, or the
repository moves to an organisation (then use a merge queue).

**`--provenance=false` stays a flag.** Without it, every rebuild gets a new
image ID and a hand-run `up -d` replaces containers though nothing changed.
`provenance: false` under `build:` is honored only since Compose 5.5.1, and
some versions refuse the whole file over it (GitHub's `ubuntu-24.04` runner,
2026-11-06), which would stop the stack and `deploy.sh`; the flag is accepted
everywhere. *Revisit when:* every Compose a deployment could run, CI's runner
included, accepts and honors the key.

**No IPv6 at the edge.** nginx publishes 80 and 443 on IPv4 only
(`0.0.0.0`, `check_compose.py`), so an IPv6 visitor falls back to IPv4 and a
server publishes no AAAA record. Published on `[::]`, Docker's proxy would
relay every IPv6 visitor from the `edge` gateway's address, one rate-limit
bucket a stranger's wrong passwords could lock. Real IPv6 needs IPv6 on
`edge` and per-address limits keyed on the visitor's /64. Behind a
dual-stack load balancer (`behind-proxy`) the limits key on a single IPv6
address today: the per-account login limits hold, the per-address ones can be
dodged. *Revisit when:* a deployment needs IPv6 at nginx, or runs behind a
dual-stack load balancer (then the /64 keying, in nginx and in Flask).

**No nginx healthcheck.** Compose never restarts an unhealthy container and
nothing depends on nginx, so a healthcheck would do nothing. Without one,
`up --wait` reports a crash-looping nginx healthy; `deploy.sh` catches that by
checking `/api/health` through nginx. *Revisit when:* a monitor or
orchestrator acts on container health.

**gixy-ng skips `hsts_header` and `try_files_is_evil_too`.** HSTS is
meaningless on the port-80 redirect server (RFC 6797 8.1) and is asserted
over HTTPS by `e2e/nginx.spec.ts`; the `try_files` warning is a performance
opinion that doesn't matter for a few static files. See the `nginx` job in
`.github/workflows/ci.yml`.

**Docker Bench warnings the stack has on purpose** (CIS Docker 1.6.0, test
VM, 2026-11-05). 4.1: `db` and `redis` start as root, but run MySQL and Redis
as their own users, and nginx's master stays root to bind 80 and 443 and read
the key, its workers not. 5.4: nginx adds `DAC_READ_SEARCH`, to read the
mode-600 key whoever owns it on the host. 5.8, 5.9, 5.14: nginx publishes 80
and 443 on every IPv4 address; it is the edge. 4.6: health checks live in the
compose file, and a platform takes its own. 4.5: Docker Content Trust is off;
the images are built on the server, never pulled. 5.13 and capabilities for
`db` and `redis`: writable root filesystems and Docker's default
capabilities, since their processes are not root and the official
entrypoints write and `chown` on first start. Sections 1-3 are the host's.
*Revisit when:* the images or their users change, or a newer CIS Docker
benchmark adds a container check.

**Unreachable CVEs in the images are low.** A scanner's finding in an image's
OS package (libexpat or libtiff in `nginx:*-alpine`; in the MySQL image, the
gosu binary, MySQL Shell's Python packages, DTLS-only OpenSSL CVEs) counts
only if this configuration can reach it: a loaded module uses it, or visitor
input reaches it. gosu runs once at start with no network, mysqlsh is never
run, and MySQL speaks TLS over TCP only. Unreachable ones are fixed by the
upstream image's rebuilds (`build --pull`) or a tag bump, not by
`apk upgrade` in a Dockerfile, which makes builds unrepeatable (hadolint
DL3017). The libraries the stack uses (OpenSSL, musl, zlib, pcre2) are judged
per CVE: a bug in compiling a regex reaches only the config's patterns, one
in matching reaches visitor input. *Revisit when:* an nginx module that uses
such a library is enabled (XSLT, image filter), the CVE is in MySQL's TLS or
authentication path, or the compose file starts running mysqlsh.

**Generic server operations are out of scope.** The template documents what
depends on how it is built (restarts, its MySQL volume's dump and restore,
what its init script and secrets do on rotation, `deploy.sh`), and leaves
what any Docker host needs to the tools made for it: alerts and uptime
checks, host metrics, log shipping, scheduled and off-host backups,
point-in-time recovery (a managed database), host hardening and its audits
(Lynis, Docker Bench, CIS). `docs/deployment.md`, "Operating in Production",
says what is not included and which tool to reach for; audits report a
missing one only where those docs fail to name it. *Revisit when:* a gap's
answer comes to depend on how this template is built.

**Keeping and shipping logs belongs to the platform.** The app and nginx log
to stdout, which a managed platform's log service ships off the host. On the
bundled Compose deployment, Docker's 3 × 10 MB per container is all there
is: it caps by size, not age, and goes with its container, so the logs reach
back to the last deploy at most. nginx's short access lines, page rate limit
and refusal sampling make rolling it over slow for one client (about 13
minutes flooding one zone) but not impossible for many. Keeping logs past a
deploy is generic server operations: "Not Included" names the tools
(journald in an untracked `docker-compose.override.yml`, Loki, Fluent Bit,
CloudWatch) rather than the template building one (user, 2026-11-05). The
docs say why it matters here: `account_deleted` events are the only record of
which accounts a restore brings back. *Revisit when:* keeping those events
past a deploy comes to need something only this template can provide.

**Email: SMTP to a managed provider, plain text, sent by the worker alone**
(user, 2026-11-09). `backend/app/utils/mail.py` speaks SMTP, which every
provider accepts, so no provider's API or webhooks are wired in and the app
does not act on bounces or complaints. Production requires TLS. Emails are
plain text: every client shows it, with no tracking, remote images or markup.
Only the worker holds the mail server's password. Nothing caps the app's
outgoing mail as a whole: the limits on whatever queues an email bound one
requester, and the provider's sending limits the rest. *Revisit when:* a
provider warns about or suspends the account over bounces or complaints
(then handle its bounce webhook and stop mailing those addresses), an email
needs HTML, or a flood of requests gets past the per-requester limits.

**Background jobs: Dramatiq, with the worker on a Redis user of its own that
may run KEYS** (user, 2026-11-09). RQ was passed over because a message names
any importable function, so a write to Redis would run code in the worker,
which holds `SECRET_KEY` and the database password; Celery for its weight.
Dramatiq runs only declared actors with JSON arguments, and each message is
signed and checked first (`SignedMessages`), under a key derived from
`SECRET_KEY` for jobs alone (`utils/keys.py`), which nothing the app shows in
Redis or the log is made with, so a Redis password alone can neither run a
job nor choose its arguments; a replayed message only repeats an email the
app asked for, with links minted in the state it was asked under. The
broker's upkeep calls `KEYS`, which `-@dangerous` refuses, so the worker
connects as `worker` (only `dramatiq` and `dramatiq:*`, plus `+keys`) and the
app's broker never runs the upkeep (`maintenance_chance=0`). `KEYS` reveals
no more than `SCAN`, which both users have; it blocks Redis a few
milliseconds per hundred thousand keys, on about one worker call in a
hundred. *Revisit when:* Dramatiq's upkeep stops calling `KEYS` (drop
`+keys`), or the keyspace reaches millions of keys.

## Frontend

**Pages load data with TanStack Query hooks and submit forms from
`onSubmit`: no React Router loaders or actions, no React form actions, no
server rendering.**
- *Loaders and actions.* A loader would fire before `ProtectedRoute`
  renders, so a signed-out visit would send an unauthenticated request and
  land on the `errorElement` instead of `/login`. Using them means moving
  both guards into loaders (`throw redirect(...)`) and rebuilding the
  "Loading..." live regions on `useNavigation`; a loader would fill the same
  cache (`queryClient.ensureQueryData`), not replace it. A route `action`
  re-runs its loader, so the two come together.
- *React form actions* (`<form action>`, `useActionState`) work with these
  forms (tried on `LoginPage`, 2026-11-07), but saved three lines, split
  validation (in `onSubmit`, to focus the first invalid field) from
  submitting, and left the last error showing during a retry. Fields stay in
  state for live error clearing and a character counter.
- *Server rendering* (Next.js, React Router framework mode) would put a Node
  server where nginx serves static files, and move sign-in to cookie
  sessions. Public pages that need search indexing would take React
  Router's build-time prerendering instead.

*Revisit when:* a page needs its data before first paint, forms read
`FormData` instead of state, or a feature needs `useOptimistic`.

**TanStack Query's retries and refetches are off** (`api/queryClient.ts`).
A query is tried once: the api client already refreshes an expired token,
and a 503 or a network error shows at once rather than after three silent
tries. Nothing refetches on window focus or reconnect by default: an infinite
list refetches every page it has loaded, and would move the rows a user is
reading or editing. A page refetches when it mounts. *Revisit when:* a page
needs fresher data than a visit gives.

**Caching: nothing beyond the defaults until a feature needs it** (user,
2026-11-08).
- *Frontend.* Every query keeps a `staleTime` of 0. A longer one hides
  changes made in another tab or device. The account query alone refetches
  on window focus, since an email change usually completes in the tab its
  link opens; the account page and navbar show the address it answers
  (`updateEmail`). Prefetching spends a request whether used or not.
- *HTTP.* Every API response is `no-store`: it carries tokens and private
  data, which an ETag or `private, no-cache` would let the browser keep on
  disk after logout. A public, non-user route sets its own header, which
  `no_store`'s `setdefault` leaves alone. nginx already caches `/assets/` for
  a year and revalidates HTML.
- *Backend.* Every read is a primary-key lookup or an index page, which
  MySQL's buffer pool serves from memory. A Redis cache is for a costly read:
  its keys need their own prefix added to the `app` ACL user in every compose
  file (`check_compose.py`) and `test_redis_acl.py`, and each entry must be
  dropped when its data changes.
- Every cache holding a user's data is emptied when the session ends or
  changes account, as `AuthProvider` does for the query cache.

*Revisit when:* a feature lets data change outside the tab that shows it,
adds a public route, or adds a read costly enough to show in
`upstream_response_time`.

**`ConfirmDialog` keeps the native `<dialog>` defaults.** A click on the
backdrop does not close it, and Tab from its last button passes through the
browser's toolbar before wrapping back. Both are how `showModal()` behaves in
every browser; overriding them means hand-written focus trapping and click
handling, which CLAUDE.md's prefer-the-built-in rule argues against.

**Pasted text is cut to a field's limit without a message.** A limited text
field uses the native `maxLength` (the notes example's, 256 characters), so
pasting more keeps the first 256, and the counter reading "0 characters
remaining" is the only sign. An
over-limit error instead means dropping `maxLength` and checking on submit,
for every limited field. *Revisit when:* users report losing pasted text, or
a field's limit is one people often reach.

**User text stored verbatim.** No server-side sanitizing; output escaping is
the render layer's job (React escapes text). Sanitizing on input corrupts data
and still misses other output contexts.

**No CORS.** The browser only calls a relative `/api`, same-origin in every
environment. Adding CORS would only widen what can call the API.

## Tooling and dependencies

**Library choices kept on purpose.** Each was weighed against the
alternative named; *Revisit when* is per item.
- *axios, not a `fetch` wrapper.* The api client relies on its interceptors,
  `error.config` for retrying the original request, JSON and non-2xx
  handling, and the `err.response.{status,data}` shape that
  `getErrorMessage`, `AccountPage` and the tests read. It costs 23 KB
  gzipped. *Revisit when:* the client needs streaming or `AbortSignal` beyond
  what axios offers, or a major release changes the interceptor API.
- *ua-parser names a session's device* (user, 2026-11-20). About 1.1 MB with
  its `ua-parser-builtins` regexes, about 1 ms a parse; a hand-written regex
  would name devices worse as user agents change. The regexes release
  monthly, so Dependabot bumps it monthly. *Revisit when:* the account page
  stops naming devices, or reduced User-Agent strings leave too little to
  parse.
- *The requirements check stays a test, not deptry.*
  `tests/unit/test_requirements.py` checks that `requirements.in` lists every
  package the backend imports; deptry needs a `pyproject.toml` section the
  backend doesn't otherwise have. *Revisit when:* an unused package slips
  into `requirements.in`, or the backend gets a `pyproject.toml`.
- *Python import contracts stay a custom test, not import-linter.*
  `tests/unit/test_import_rules.py` does what its `layers` and `protected`
  contracts do and finds new features by itself; import-linter (2.15) skips
  packages without an `__init__.py`, so it would need five empty ones, a
  scaffold step per feature, and five dev packages. *Revisit when:* the
  feature packages get `__init__.py` for another reason, or the rules outgrow
  the test (more layers, per-feature exceptions).
- *Frontend folder rules stay a custom ESLint rule, not
  `eslint-plugin-boundaries`.* `relative-within-folder` (about 25 lines) and
  the `@/` patterns enforce the one-way imports; `boundaries` would need
  `eslint-plugin-import`'s resolvers for the `@/` alias, and the planted
  tests would stay anyway. *Revisit when:* the rules outgrow the custom rule.
- *The color guard stays a Vitest test, not stylelint.*
  `styles/__tests__/stylesheets.test.ts` also refuses unused and undefined
  tokens, which stylelint does not cover, and stylelint would add a CLI, a
  config and a CI step. *Revisit when:* the CSS needs rules a stylelint
  preset already has, or the hand-written check misses a case.
- *pytest-cov stays.* Plain `coverage run` would save one small package for a
  rewrite of `run_tests.sh`'s flags. *Revisit when:* pytest-cov lags a pytest
  major release.
- *The JSON log formatter stays hand-written.* `JsonFormatter` is a few
  lines; `python-json-logger` would add a dependency for nothing the app
  needs. *Revisit when:* a log service needs a specific schema (Elastic ECS,
  Datadog), lines need tracing ids, or the formatter grows past about 40
  lines.
- *The API's types come from JSON Schema, not OpenAPI*
  (`export_schemas.py`, `npm run api-types`). Pydantic writes JSON Schema
  itself, nothing reads an OpenAPI document, and openapi-typescript requires
  TypeScript 5. The types cover bodies, not routes. *Revisit when:* the API
  needs published docs or a typed client per route.
- *No `engines` field, the `react-router-dom` package, unhashed Python
  locks.* CI and Docker pin one Node major (`check_versions.py`), the shim
  costs nothing at runtime, and Dependabot plus exact pins cover the locks.
  *Revisit when:* a contributor hits a Node mismatch, React Router drops the
  shim, or a supply-chain incident touches PyPI.

**Ruff's `select` lists every rule in full.** Ruff's own default set is far
wider than pyflakes (`I`, `SIM`, `B`, `RUF`, `UP` and about 30 more
families) and changes between releases, so `extend-select` would turn on
whatever the installed ruff defaults to. *Revisit when:* the repo chooses to
adopt ruff's defaults.

**No mutation-testing tool.** New tests are mutation-checked by hand (CLAUDE.md
Test Architecture). *Revisit when:* the suites grow past what spot checks can
cover; mutmut and Stryker are the candidates (SOURCES.md, Testing).

**Dev keeps a debug toggle.** `.env.dev` turns Flask debug on; `FLASK_DEBUG=0
./run_dev.sh` turns it off for one run. Production forces it off in
`ProductionConfig`.

## Licensing

**The template is MIT-0, and its copyright is its owner's.** Under MIT every
app built from the template would have to carry its notice; MIT-0 drops that,
so README's step 6 can tell a new app to replace `LICENSE` outright. The
first commit came from a university email address, but the template has
always been the owner's personal project, made outside any university
employment, grant or course, so `LICENSE` names the owner alone. *Revisit
when:* the owner wants attribution from derived apps, or the university
raises a claim.

**Images are run, not distributed.** The MySQL image, and the Debian and
Alpine userlands under the backend and nginx images, contain GPL and LGPL
code; Dramatiq is LGPL-3.0, installed unmodified. Two backend packages,
`ordered-set` (MIT) and `ua-parser-builtins` (Apache-2.0), ship no license
file in their wheels. Running all of it on the operator's own servers
creates no duty: source offers and notices apply to copies handed to others.
`deploy.sh` builds the images on the server and pushes them nowhere, and a
private registry for one's own deploys is not distribution either. The
frontend's notices do ship (`third-party-licenses.txt`), since every visitor
receives the bundle. *Revisit when:* images are pushed anywhere others can
pull them, shipped to anyone else to run, or Dramatiq is patched.

**Redis 8 is used unmodified under its tri-license** (RSALv2, SSPLv1 or
AGPLv3). The stack runs `redis:8.10-alpine` unmodified as a private store
users never reach, which none of the three restricts. *Revisit when:* Redis
is modified or offered to customers as a service, or a lawyer prefers Valkey
(BSD-3-Clause).

**Legal placeholders are not enforced at build.** Nothing stops a production
image from serving the placeholder `OPERATOR` values in
`frontend/src/appInfo.ts`, `contact@example.com` in `security.txt`, or the
"Placeholder" banner on the legal pages. `docs/personal-data.md`'s "Before
launch" list is the only safeguard: a build check would have to tell the
production image apart from the test stack's, which serves the same
placeholders on purpose. *Revisit when:* the first real deployment is
prepared.
