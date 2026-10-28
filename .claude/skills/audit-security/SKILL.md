---
name: audit-security
description: Security review against OWASP ASVS Level 2 and the Cheat Sheets (code, config, containers), dependency vulnerabilities and unused packages, and a local scan of the running test stack. Live checks against a deployment are skipped until one exists.
argument-hint: "[code|deps|scan]"
disable-model-invocation: true
context: fork
---

# /audit-security

First read `.claude/skills/_audit-shared/RULES.md` and follow it throughout.
Then read `CLAUDE.md`, plus `SOURCES.md` (Cross-cutting: security, and each
layer's section) and `DECISIONS.md` from the same folder as RULES.md.
DECISIONS.md's accepted trade-offs matter most here: do not re-report them.
This check runs Docker: record all four Timings (RULES.md, Report).

**Scope:** `$ARGUMENTS`. If empty, run all three parts.

Think like an attacker with the source code. For every finding, give the
attack (who, from where, doing what, gaining what), not just the weakness.

## 1. code: application and configuration review

Read all of `backend/app/`, `frontend/src/` (except tests), `nginx/`, the
Dockerfiles and compose files. Walk the ASVS 5.0 Level 2 chapters that apply to
this app and record what each one turns up:

- **Authentication and sessions:** password policy and NFKC handling,
  hashing parameters and the concurrency limit, login timing, rate limits per
  IP and per account (key functions, `normalize_email`, ProxyFix with
  `TRUSTED_PROXY_COUNT`), access and refresh token lifetimes, rotation (the
  Lua script, the race), revocation, `logout-all`, the session cap, cookie
  flags (`Secure`, `HttpOnly`, `SameSite`, path), CSRF double-submit on
  refresh, `clear-cookies`, what happens to sessions when a user is deleted.
- **Access control:** every route that touches user data requires a token
  and scopes queries to `current_user` (try reading or paginating another
  user's notes via the cursor, and `PUT`/`DELETE /api/notes/<id>` on another
  user's note: both must answer 404 exactly like a missing id). Lint refuses
  `get_jwt_identity()` (ruff `TID251`). Account deletion
  (`POST /api/account/delete`): a wrong password answers 403
  `WRONG_PASSWORD` and logs `wrong_password`; it revokes every session before
  deleting, and answers 503 with nothing deleted when Redis cannot revoke them.
- **Input and output:** every request body and query passes through a Pydantic
  schema; size limits at nginx and Flask; email and password normalization
  (lint already refuses SQL built from strings, `dangerouslySetInnerHTML`,
  `eval`, `subprocess` and `os.system`); error responses leak no stack
  traces, SQL, or internal hostnames.
- **Secrets:** nothing secret in git history
  (`git log -p --all -S 'SECRET_KEY=' -- . ':!*.example' ':!*.examples' ':!.env.dev' ':!.env.test' ':!.claude'`
  plus a scan for key-shaped strings), `ProductionConfig`'s secret checks,
  the root DB password reaching only `db`, and the migration user's only
  `migrate`, secrets never logged (grep the logging calls).
- **Transport and headers:** TLS config, HSTS, CSP, frame, referrer,
  permissions and content-type headers; HTTP→HTTPS; the catch-all host.
  In `behind-proxy` mode (`nginx/servers/behind-proxy.conf.template`,
  `nginx/server-mode.sh`): can a client skip the `X-Forwarded-Proto`
  redirect, set its own address through `X-Forwarded-For`
  (`NGINX_TRUSTED_PROXIES`), or get anything but `/api/health` from the
  catch-all?
- **Containers and Redis:** non-root users, capabilities, read-only roots,
  networks (can nginx reach MySQL? should it?), exposed ports, the Redis ACL,
  and the MySQL privileges of the app's and the migration user
  (`db/init/01-app-user.sh`), checked live.
- **Denial of service:** body limits, connection limits, hashing slots, slow
  clients, unbounded queries or lists, Redis memory growth.
- **What is missing:** ASVS 5.0 L2 requirements the app neither meets nor has
  recorded in DECISIONS.md. Report each one as a gap with its ASVS 5.0 number.
  Group gaps that one feature would close (password reset, MFA, email
  verification) into one finding each. Check the security events
  `utils/log.py` logs against ASVS 5.0 chapter 16 (Security Logging) rather
  than reporting logging as missing.

## 2. deps: dependencies

- Python: `pip-audit --no-deps --disable-pip -r backend/requirements.txt` and
  the same for `backend/requirements-dev.txt` (the locks pin every package, so
  nothing needs resolving; if `pip-audit` isn't
  installed in the venv, run it with `pipx run pip-audit`, or install it into
  a throwaway venv in your scratch directory, never into the project venv).
- JavaScript: `npm audit` in `frontend/` (all deps) and `npm audit --omit=dev`
  (what ships).
- Dependabot: first confirm alerts are enabled
  (`gh api repos/{owner}/{repo}/vulnerability-alerts` answers 204), since an
  empty alert list looks the same either way; then
  `gh api repos/{owner}/{repo}/dependabot/alerts --paginate --jq '.[] | select(.state=="open" or .state=="auto_dismissed")'`
  and open Dependabot PRs (`gh pr list --author app/dependabot`). An
  `auto_dismissed` alert is a finding: an auto-dismiss rule (such as the
  "Dismiss low impact alerts" preset) is on again and hides advisories.
  So is an `npm audit` or `pip-audit` hit missing from the alert list.
- Images: are the pinned base images (Dockerfiles, compose files, the
  hadolint digest in CI) current releases of supported versions? Then scan
  the built images for OS-package CVEs, which tag checks can't see:
  `docker run --rm -v //var/run/docker.sock:/var/run/docker.sock aquasec/trivy image --severity HIGH,CRITICAL --ignore-unfixed <image>`
  for the backend and nginx images (build them first, or scan the stack's)
  and the MySQL and Redis images.
- Unused or misplaced packages: compare `requirements.in` and
  `package.json` against actual imports (`backend/app`, `frontend/src`), config
  files and scripts. A package used only by tests belongs in the dev lists.

Rate every CVE by reachability, as RULES.md rates everything by impact: a
critical or high CVE in shipped code that this app's configuration can reach
is a blocker; one it cannot reach (the module isn't loaded, the input never
reaches it) is low, with the reasoning stated, and its fix is still an image
rebuild or upgrade. Dev-only CVEs are rated by whether they can reach CI or a
developer's machine.

## 3. scan: the running test stack

Bring up the E2E stack (follow RULES.md's Docker and certificate rules):
`docker compose --env-file .env.test -f docker-compose.test.yml --profile e2e up -d --build --wait`.
From the host, target `https://localhost:8443`; from scanner containers,
join nginx's network namespace and target `https://localhost` as RULES.md
describes. Nothing else.

- **Headers and TLS:** `curl -skI` on `/`, `/assets/<a real asset>`, `/api/health`,
  an unknown path, and an unknown Host header. Run testssl.sh:
  `docker run --rm --network container:<nginx> drwetter/testssl.sh --quiet localhost:443`.
  Locally it always grades the self-signed certificate "T" and flags the
  missing SAN, chain and OCSP: expected, not findings.
- **ZAP:** Java sends no TLS server name for a dotless host like
  `localhost`, so nginx refuses ZAP's TLS connection and ZAP reports an empty,
  clean-looking scan. Bridge it: in nginx's network namespace, run
  `alpine/socat TCP-LISTEN:8081,fork,bind=127.0.0.1 OPENSSL:localhost:443,verify=0,snihost=localhost`
  (detached), and point ZAP (also in that namespace) at `http://localhost:8081`.
  - Front end: `zap-baseline.py -t http://localhost:8081 -I`.
  - API: `zap-api-scan.py` with a small OpenAPI file you write in the
    scratch directory from each feature's `backend/app/*/routes.py` (every route, method and
    body), a Bearer token for a registered test user injected with
    `-config replacer.full_list(0).description=auth -config replacer.full_list(0).enabled=true -config replacer.full_list(0).matchtype=REQ_HEADER -config replacer.full_list(0).matchstr=Authorization -config replacer.full_list(0).replacement="Bearer <token>"`,
    and `-config scanner.delayInMs=60` to stay under nginx's per-IP limit.
    The access token lasts 15 minutes; refresh it if the scan runs longer.
  - After each scan, grep its log for `Failed to access` and check its URL
    count. A scan that reached nothing is a failed step, not a pass.
  - Triage every alert. Most are false positives for an SPA plus JSON API;
    report only what holds up, with the request that shows it.
- **Hand probes** the scanners can't do, on the test stack: replay a rotated
  refresh token, send a refresh without the CSRF header, read another user's
  notes via the cursor, edit and delete another user's note by id, send a
  17 KB body, send malformed JSON, log in
  with a password that differs only by Unicode normalization, and delete an
  account with a wrong password, then with the right one (every session of
  that account must then be refused).
- **`behind-proxy` probes,** once the test stack is down (both use the
  `app_test` project): bring up the platform smoke stack
  (`docker compose --env-file .env.test -f docker-compose.test.yml -f .github/smoke/platform.yml --profile platform up -d --build --wait`,
  nginx on `127.0.0.1:8081`, the host standing in for the load balancer;
  tear down with `--profile platform --profile e2e down -v`). A request
  whose `X-Forwarded-Proto` isn't `https` must redirect; a forged leftmost
  `X-Forwarded-For` hop must not become the client's address in nginx's
  and the backend's logs (the rightmost untrusted one must); any path but
  `/api/health` with a bare-IP `Host` gets no response. The host's requests
  come from a trusted address, so judge an untrusted sender's
  `X-Forwarded-For` from the `real-ip.conf` that `nginx/server-mode.sh`
  writes (`docker exec app_test-platform-nginx-1 cat /etc/nginx/conf.d/real-ip.conf`).

Tear the test stack down. Then, **for the rate-limit probes only**, bring up
the production-config stack (RULES.md): the test stack runs `IntegrationConfig`,
which turns Flask's limits off and trusts no proxy. Check each login limit
(`backend/app/auth/routes.py`): 5 failures a minute for one account from one
address answer 429, while the same account still logs in from a second
address (a stranger's guesses lock out only the stranger); 100 failures an
hour for one account from rotating addresses answer 429 from any address;
successful logins count toward neither; different spellings of the same
email share one counter; and a forged `X-Forwarded-For` cannot change the
address the limits key on. Then account deletion's: 5 wrong passwords a
minute for one user answer 429, and its wrong passwords count toward the
same hourly per-account budget as failed logins (`account_password_limit`),
so failed logins plus wrong deletion passwords reaching 100 answer 429 on
both routes. Tear it down.

**Skipped until deployed** (list under *Skipped*): Observatory and SSL Labs
against the real domain, Docker Bench and CIS on the host, SSH, firewall and
Fail2ban drift. The OWASP Testing Checklist and WSTG items that need a real
deployment go here too.

## Out of scope
Fixing anything. Infra style and simplicity (`/audit-infra`).

Write the report as RULES.md describes, with ID prefix `SEC`. For each
finding, include the ASVS requirement or cheat sheet it comes from, if any.
