# Audit rules

Every `/audit-*` check follows these rules. Read this whole file before starting.

## What the audits are for

This repository is the template, or an app built from it (README, "Starting
a New App"): in an app, read "the template" as the app. Every run should
leave it closer to bulletproof. In priority order:

1. **Secure and production-grade.** Correct under failure, abuse and load.
2. **Test-driven.** Every behavior that matters is pinned by a test that can fail.
3. **Lean.** Little code, few dependencies, few moving parts. Removing
   something is as valid a finding as adding something. A recommendation to
   add anything (a dependency, a service, a config knob, a layer) must name the
   concrete gap it closes; "best practice says so" is not enough.
4. **Easy to scaffold** (the template's alone: an app replaces it with its
   own top rule, or drops it). A new app replaces the example feature and
   renames a few things. Anything that makes that harder (example code
   leaking into shared code, names tied to "notes" or "app", steps missing
   from README's "Starting a New App") is a finding.

## Sources of truth

- **CLAUDE.md is the spec.** It states how every layer works and why. Check
  the code against each claim it makes in your scope. A claim the code doesn't
  honor is a finding: either the code is wrong or CLAUDE.md is stale. Say which,
  with evidence. Do not copy CLAUDE.md's facts into findings as if new.
- **`SOURCES.md`** (next to this file) lists the outside standards per layer
  (OWASP, official docs, reference templates). Its table at the end says which
  sources your check starts with. A source's advice is a prompt to check, not
  an order; adopt it only where it fixes a real gap in this app.
- **`DECISIONS.md`** (next to this file) lists accepted trade-offs and known
  gaps. Do not report them as findings. Report an entry only if its *Revisit
  when* condition has come true or the code no longer matches it.
- **`OPEN-ISSUES.md`** (next to this file) is the running list of open
  work. Check every finding against it and against `DECISIONS.md`. A finding
  either already documents is never relisted. When this run shows something
  material the entry lacks (it is worse, wider, or has new evidence), propose
  an edit to that entry in the *Recording plan* instead, tagged
  `(open: <issue>)` or `(decided: <entry>)`, and count it under excluded.
- **Read files from disk.** A copy of CLAUDE.md or any other file already in
  your context may be older than the working tree. Read it again before
  relying on it.
- **Code beats prose.** Read the actual file before claiming anything about it.
  If a claim can be checked by running something (a test, a curl, a grep, a
  container), run it. Never report a guess as a finding; if you could not
  verify something, list it under *Unverified* with what would settle it.

## Boundaries

Audits are **read-only** with respect to the repository:

- Do not edit, create or delete tracked files, and do not commit, push, or
  change branches in the main working tree. The only file you write is your
  report (below). That includes `OPEN-ISSUES.md` and
  `DECISIONS.md`: the report's *Recording plan* proposes what goes in them,
  and the main conversation records it once the user approves.
- **Project names.** `<dev>`, `<test>` and `<prod>` stand for the `name:` at
  the top of `docker-compose.dev.yml`, `docker-compose.test.yml` and
  `docker-compose.yml` (`app_dev`, `app_test` and `app` in the template);
  read them there. The audits' production-config stack is `<prod>_audit`.
- Do not touch `.env.prod`, or the `<dev>` and `<prod>` Compose projects or
  their volumes. They hold the user's data.
- Checks that need running services use one of two throwaway stacks (plus
  `/audit-infra`'s Deploy smoke run, below), never two at once. Only one check may run Docker at a time (the `/audit`
  orchestrator runs them one after another), and each tears its stack down
  when done, volumes included.
  - The **test stack**: `docker-compose.test.yml`, project `<test>`, ports
    3307, 6380, 1026 and 8026 (Mailpit's SMTP and API), 8080, 8443. Tear
    down with
    `docker compose --env-file .env.test -f docker-compose.test.yml --profile e2e down -v`.
  - A **production-config stack** for checks that need production behavior
    (persistent volumes, restart policies): `docker-compose.yml` with
    `-p <prod>_audit`, an env file written to the scratch directory from
    `.env.prod.example` (keep its `COMPOSE_PROFILES` line: without it `db`
    and `redis` don't start), with fresh random secrets (`openssl rand -hex 32`),
    `SERVER_NAME=localhost` and `EDGE_SUBNET_PREFIX=10.217.9` (the default
    `10.217.0` clashes with a local production stack's edge network, and
    the test stack uses `10.217.1`), plus a scratch override file that rebinds
    nginx to `127.0.0.1` (`ports: !override ["127.0.0.1:80:80", "127.0.0.1:443:443"]`),
    so nothing listens on the network. Never use the bare project name
    `<prod>`. Tear it down with the same `-p <prod>_audit` and `-f` flags
    plus `down -v`.
    Email and the breach check, as audit-recovery proved on 2026-11-09:
    - **A mail sink the worker trusts.** Production refuses Mailpit's plain
      `smtp://` and the example's mail values, and the worker stops without
      valid ones. Make a throwaway CA and a leaf certificate for `mailsink`
      in the scratch directory (the leaf needs `subjectAltName=DNS:mailsink`,
      `keyUsage=critical,digitalSignature,keyEncipherment`,
      `extendedKeyUsage=serverAuth`, `subjectKeyIdentifier=hash` and
      `authorityKeyIdentifier=keyid,issuer`, since Python checks strictly;
      `openssl verify -x509_strict` must pass; run `openssl` with
      `MSYS_NO_PATHCONV=1` on Git Bash for its `-subj` paths). In the env
      file set `EMAIL_URL=smtp+starttls://audit:<openssl rand -hex 32>@mailsink:1025`
      and `EMAIL_FROM="Audit <no-reply@audit.invalid>"`. In the override:
      the worker gets `environment: {SSL_CERT_FILE: /mailca/ca.pem}` and the
      CA directory mounted read-only at `/mailca`; a `mailsink` service runs
      the test stack's Mailpit image with `MP_SMTP_TLS_CERT`,
      `MP_SMTP_TLS_KEY` (the leaf, mounted read-only at `/certs`),
      `MP_SMTP_REQUIRE_STARTTLS=true` and `MP_SMTP_AUTH_ACCEPT_ANY=true`, on
      `networks: [edge]`, its API on `127.0.0.1:8027:8025`, `restart: "no"`.
      Mailpit forgets its messages when restarted: count by address.
    - **No call to Pwned Passwords:** the override gives the backend
      `environment: {PWNED_PASSWORDS_URL: ""}` (empty turns the check off).
    - **Accounts** go through sign-up as a user's would: `POST
      /api/auth/register {"email"}` (202), then the newest message to that
      address from the sink's API (`GET /api/v1/search?query=to:"<addr>"`,
      then `GET /api/v1/message/<ID>`, its `Text`), the `token` from the
      link's fragment (`/signup/complete#token=...`), and `POST
      /api/auth/register/complete {"token", "password", "terms_version"}`.
      The password: 15 characters or more, holding neither the address nor
      the app's name (`PASSWORD_GUESSABLE`). Sign-up allows 10 links an hour
      per IP, 3 an hour and 6 a day per address, and 10 completions an hour
      per IP: between batches, delete the `LIMITS:*regist*` keys as the
      app's Redis user (SCAN, since it may not run KEYS; `*register*`
      alone misses `auth.complete_registration`), and give each account a
      fresh address: the per-address budget, shared with the email change,
      is keyed by its scope, `emails-to-address`, which that pattern does
      not match.
  - **Deploy smoke** (`python .github/scripts/smoke_deploy.py`,
    `/audit-infra`'s deploy layer only): its own clone and project
    `deploy_smoke`, subnet `10.217.8`, nginx on ports 80 and 443 of
    **every** interface while it runs, so not beside the production-config
    stack or a local production stack. It tears itself down, images
    included; check `docker ps -a --filter name=deploy_smoke` is empty
    afterwards.
- The audits never touch a deployed server, the maintainer's test server
  included. Never scan, SSH into, or load-test anything other than
  localhost. A step that needs a real deployment is reported under *Skipped*
  with the reason.
- "No Docker" (when the orchestrator says so) means starting no containers.
  Docker commands that only read or validate (`docker info`, `docker ps`,
  `docker compose ... config --quiet`) are always allowed.
- Scratch work (worktrees, probe files, scan output) goes in the session's
  scratchpad or the system temp directory, never in the repository. One
  exception: the stacks mount TLS certificates from the gitignored
  `nginx/certs/`. If it has no `fullchain.pem`/`privkey.pem` pair, create a
  self-signed one there as CI does
  (`openssl req -x509 -nodes -days 30 -newkey rsa:2048 -keyout nginx/certs/privkey.pem -out nginx/certs/fullchain.pem -subj "/CN=localhost"`),
  and say so in the report. Never overwrite an existing pair.
- Build output goes to scratch too: `npm run build -- --outDir <scratch>/dist`.
- **Requests from the host:** nginx drops bare IPs, and on Windows plain
  `localhost` can stall about 2s per connection while IPv6 is tried first. Use
  `curl -sk -m 10 --resolve localhost:8443:127.0.0.1 https://localhost:8443/...`
  (port 443 for the production-config stack). Always pass `-m 10`: curl on
  Windows can hang for minutes on some requests. Foreground `sleep` may be
  blocked; to wait out a rate-limit window, poll in an until-loop with a
  deadline, and allow about 65s, since Flask's windows start at the first
  request, not on the minute. nginx limits `/api` to about
  30 requests per second per IP (`NGINX_API_RATE`) and the page (`/` and the
  files beside it) to 10 (`NGINX_PAGE_RATE`), so pace timing runs, or expect
  429s.
- **Verify privileges and limits live**, not from a script's output or its
  test: for example, `SHOW GRANTS` and an actual `CREATE TABLE` as the app's
  MySQL user, or an actual forbidden command as the app's Redis user.
- **Scanning a stack from a container:** nginx answers only its
  `SERVER_NAME` (`localhost` in both stacks) and drops other hosts, so
  `host.docker.internal` gets nothing back, and an empty scan can look clean.
  Run scanner containers inside nginx's network namespace instead, so
  `localhost` reaches it: `docker run --rm --network container:<nginx container name> <image> ... https://localhost:443`
  (find the name with `docker compose ... ps nginx --format '{{.Name}}'`).
  Java-based tools (ZAP) send no TLS server name for `localhost` and are
  refused; `/audit-security` describes the socat bridge for them.
  Always confirm a scan saw real responses (for example, its request count
  or a known header) before reporting it clean.

## Environment

- Windows with Git Bash (POSIX syntax) and PowerShell; Docker Desktop.
- Backend tools: `source backend/.venv/Scripts/activate` (or `.venv/bin/activate`
  on Linux/macOS). Frontend: `npm` in `frontend/`.
- CI runs on pushes to `main` and on pull requests: ruff (the backend and
  `.github/scripts`), ESLint, mypy and tsc (each with a planted case per
  rule), both unit suites with coverage, the same again after
  `remove_examples.py` (the Scaffold job), compose validation, the db init
  script check, zizmor, ShellCheck, a license, required-checks, toolchain-version,
  documented-build and whitespace check, hadolint and gixy-ng.
  Integration, E2E, Platform smoke and Deploy smoke run on `main`, on pull
  requests, and daily. Check the
  `on:` blocks in `.github/workflows/` if in doubt. **Read CI results instead
  of re-running them:** `gh run list --commit $(git rev-parse HEAD)` first,
  then per workflow (`gh run list --branch main --workflow CI --limit 5`, and
  the same for `"Integration & E2E"`; unfiltered lists fill up with Dependabot
  and code-scanning runs), and `gh run view <id> --log-failed`. Playwright
  retries twice in CI, so a flaky test passes silently: search the E2E job's
  log for `flaky`.
  CI results count only for the commit they ran on: on a branch with no run
  for HEAD, or with a dirty tree, diff it against `main`
  (`git diff --stat main...HEAD -- . ':!.claude' ':!*.md'`) and run locally
  what the changed files affect. If that diff is empty, `main`'s CI results
  stand for this branch. If `gh` is
  unavailable, say so and run locally instead.
- Scratch worktrees (`git worktree add <scratch>/<name> HEAD`) have no
  `backend/.venv` or `frontend/node_modules`. Backend: run the main tree's
  venv from inside the worktree (`<repo>/backend/.venv/Scripts/python -m pytest`,
  or `.venv/bin/python` on Linux/macOS). Frontend: link the main tree's
  modules. On Windows use PowerShell
  (`New-Item -ItemType Junction -Path <worktree>\frontend\node_modules -Target <repo>\frontend\node_modules`;
  `cmd //c mklink` from Git Bash mangles the backslashes); elsewhere `ln -s`.
  Or run `npm ci` if the lockfile changed.
- **Removing a worktree: unlink first.** Delete the `node_modules` link **in
  a call of its own** (Windows: `cmd /c rmdir <worktree>\frontend\node_modules`,
  which removes the junction, not its target; elsewhere `rm` the symlink).
  In a separate call, check that `<worktree>/frontend/node_modules` is gone
  (`Test-Path` is False) and `<repo>/frontend/node_modules` still exists.
  Only then run `git worktree remove --force <path>`. Never put the unlink
  and the removal in one command: if the call is refused as a whole, the
  next step removes the worktree with the link still in place, which can
  delete the main tree's modules through it.
- Gotchas: `run_tests.sh integration` ends with `down -v`, which kills an E2E
  stack using the same project. Playwright reuses a running stack locally
  (`reuseExistingServer`), so tear down before rerunning E2E and pass
  `--build` when backend code changed.

## Turn findings into guards

For every finding, ask: could a lint rule, test, CI job or type check catch
this class of problem next time? If yes, the fix must include that guard (the
**Prevent** column). The goal is for each audit to leave less for the next one
to do by hand. A check that keeps finding the same mechanical problem should
recommend moving it into CI and dropping it from the prompt.

## Severity

| Severity | Meaning |
|---|---|
| **blocker** | Exploitable vulnerability, data loss, a red test or CI run, a secret in git, or production behavior that contradicts CLAUDE.md in a way users would hit. Release is blocked. |
| **high** | Real defect or exposure needing an unusual condition; a missing test for security-relevant or data-integrity behavior; a dependency CVE rated high or critical. |
| **medium** | Defect in an edge case; drift between code and CLAUDE.md or README; a test that cannot fail; a meaningful deviation from a SOURCES.md standard. |
| **low** | Hardening, simplification, consistency, or clarity with modest payoff. |
| **nit** | Wording or style. Report at most five; skip the rest. |

Rate by impact on a real deployment of an app built from this template, not by
how much work the fix is. `/audit-legal` maps these levels onto legal
exposure in its own table.

## Report

Write the report to `temp/audits/YYYY-MM-DD-<check>.md` (today's date, the
check's name, e.g. `2026-10-09-audit-infra.md`; `temp/` is gitignored). If a
report for the same check and date exists, overwrite it.

```markdown
# <check> — YYYY-MM-DD

Commit: <git rev-parse --short HEAD> (<branch>), working tree clean|dirty
Scope: <what was covered; arguments passed, if any>
Verdict: PASS | FINDINGS | BLOCKED   (BLOCKED if any blocker)
Counts: blocker N, high N, medium N, low N, nit N; excluded N (already documented)
Timings: start HH:MM, first container HH:MM, last teardown HH:MM, end HH:MM

## Findings

| ID | Sev | Location | Finding | Evidence | Fix | Prevent |
|---|---|---|---|---|---|---|
| INFRA-1 | high | `nginx/...:42` | One sentence. | What you read or ran that shows it. | Concrete change. | Guard that would catch it, or "—". |

## Compared with last run
Read the most recent earlier report for this check in `temp/audits/`; if
there is none, write "First run." and nothing else here.
New: IDs not in the last report. Excluded: what this run saw that
OPEN-ISSUES.md or DECISIONS.md already documents, one line each (the issue
or entry, and whether this run adds anything material). Resolved: the
earlier findings that are now fixed.
Recurring: IDs also in the last report. A finding that was fixed and is
back says so, and its proposed fix must remove the cause (a guard, a test, or
a structural change such as one line per rule), not repeat the patch.

## Proposed PRs
Every finding not proposed for OPEN-ISSUES.md or DECISIONS.md goes into
exactly one PR, lows and nits included.
### PR 1: <title>
Fixes: <IDs>
Changes: <file by file, from the Fix column>
Guards: <from the Prevent column, or "—">
Tests: <suites to run, tests to add and mutation-check>

## Decisions for you
One entry per finding whose fix needs the user's choice now (which option,
whether to fix or record it, a wording): the question, the options with
the recommended one first, and what each changes. "None." if there are none.

## Recording plan
| ID | Sev | Goes to |
|---|---|---|
| INFRA-1 | high | PR 1 |
| INFRA-2 | low | OPEN-ISSUES.md: <existing issue it merges into>, or new issue under <group> |
| INFRA-3 | nit | DECISIONS.md: new entry (below), or amends "<entry title>" |

Edits to documented entries (excluded items with something material to
add): one line each, `(open: <issue>)` or `(decided: <entry>)`, and the text
to add. "None." if there are none.

## Proposed DECISIONS.md entries
Findings that look deliberate: the entry you would add, for the user to accept or reject.

## Verified
Short bullets of important claims you checked and found true (one line each).

## Unverified / Skipped
What you could not check, and why (no deployment, Docker unavailable, ...).
```

**Proposed PRs:** group findings that touch the same files or would be
fixed together, keep a risky change (auth, data, deploy) apart from
routine ones, and order the PRs by severity, then by what depends on
what. An excluded item gets no PR, unless this run's evidence makes it
urgent: then it is a finding again, and its line in *Compared with last run*
says why.

**Recording plan:** one row per finding, every ID in *Findings* exactly
once; check the count matches the Counts line. A finding in a PR is
recorded with that PR; one that overlaps an issue in OPEN-ISSUES.md or a DECISIONS.md
entry is combined with it rather than added beside it.

**Timings:** run `date +%H:%M` when you start, just before your first
container starts, just after your last teardown, and when you finish, and
write the four times on the Timings line. A check that starts no containers
gives `start` and `end` only. The times show how much of each check's run
uses Docker, which decides whether Docker checks could overlap.

Write the report with the Write tool, not a shell heredoc (backticks and pipes
in the tables break shell quoting). When citing line numbers, read each file
on its own; line numbers from several files concatenated together are wrong.

**Overlap with other checks:** if a finding belongs mainly to another
check's area (an accessibility problem found during the code check), report
it briefly and tag it `(also /audit-<other>)`; don't investigate further. If
another check's report from the same day in `temp/audits/` already has it,
cite that ID (`see INFRA-1`) instead of reporting it again, unless you add
new evidence. The orchestrator merges what remains.

ID prefixes: `INFRA`, `TEST`, `SEC`, `REC`, `CODE`, `A11Y`, `DOCS`, `SCAF`,
`LEGAL`.
Order findings by severity. Give each one a precise `file:line`.

When done, reply with **only** the following, in this order (the report
holds the detail):
1. The verdict, and an accounting: how many findings, by severity; how many
   items were excluded as already documented, and which (issue or entry).
2. Grouped by proposed PR: its title, then every finding it fixes, one line
   each with its own ID (never a range, never folded into another's line),
   then any decision that shapes that PR, in full, right there.
3. The same for the findings going to OPEN-ISSUES.md and to DECISIONS.md,
   each group with its decisions.
4. The report path, and a request to answer the decisions so the findings
   can be recorded as the *Recording plan* says.
Check by script that every ID in the report appears in the reply exactly
once.
