# Audit rules

Every `/audit-*` check follows these rules. Read this whole file before starting.

## What the audits are for

This repository is a template, and every run should leave it closer to
bulletproof. In priority order:

1. **Secure and production-grade.** Correct under failure, abuse and load.
2. **Test-driven.** Every behavior that matters is pinned by a test that can fail.
3. **Lean.** Little code, few dependencies, few moving parts. Removing
   something is as valid a finding as adding something. A recommendation to
   add anything (a dependency, a service, a config knob, a layer) must name the
   concrete gap it closes; "best practice says so" is not enough.
4. **Easy to scaffold.** A new app replaces the example feature and renames a
   few things. Anything that makes that harder (example code leaking into
   shared code, names tied to "notes" or "app", steps missing from README's
   "Starting a New App") is a finding.

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
  report (below).
- Do not touch `.env.prod`, or the dev (`app_dev`) and production (`app`)
  Compose projects or their volumes. They hold the user's data.
- Checks that need running services use one of two throwaway stacks, never
  both at once. Only one check may run Docker at a time (the `/audit`
  orchestrator runs them one after another), and each tears its stack down
  when done, volumes included.
  - The **test stack**: `docker-compose.test.yml`, project `app_test`, ports
    3307, 6380, 8080, 8443. Tear down with
    `docker compose --env-file .env.test -f docker-compose.test.yml --profile e2e down -v`.
  - A **production-config stack** for checks that need production behavior
    (persistent volumes, restart policies): `docker-compose.yml` with
    `-p app_audit`, an env file written to the scratch directory from
    `.env.prod.example` (keep its `COMPOSE_PROFILES` line: without it `db`
    and `redis` don't start), with fresh random secrets (`python -c "import secrets; print(secrets.token_urlsafe(48))"`),
    `SERVER_NAME=localhost` and `EDGE_SUBNET_PREFIX=10.217.9` (the default
    `10.217.0` clashes with a local production stack's edge network, and
    the test stack uses `10.217.1`), plus a scratch override file that rebinds
    nginx to `127.0.0.1` (`ports: !override ["127.0.0.1:80:80", "127.0.0.1:443:443"]`),
    so nothing listens on the network. Never use the bare project name `app`.
  - Project names here (`app_test`, `app_dev`, `app_audit`) are the
    template's defaults. In an app built from the template, read the real
    names from each compose file's `name:` and use those instead.
    Tear down with the same `-p app_audit` and `-f` flags plus `down -v`.
- There is no deployed server (see DECISIONS.md, Known gaps). Never scan, SSH
  into, or load-test anything other than localhost. A step that needs a real
  deployment is reported under *Skipped* with the reason.
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
- CI runs on pushes to `main` and on pull requests: ruff, ESLint, both unit
  suites with coverage, the same again after `remove_examples.py` (the
  Scaffold job), compose validation, zizmor, a license, required-checks,
  toolchain-version and whitespace check, hadolint and gixy-ng.
  Integration, E2E and the Platform smoke job run on `main`, on pull
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
- **Removing a worktree: unlink first.** Delete the `node_modules` link on its
  own before removing the worktree (Windows: `cmd /c rmdir <worktree>\frontend\node_modules`,
  which removes the junction, not its target; elsewhere `rm` the symlink).
  Then check `<repo>/frontend/node_modules` still exists, and only then run
  `git worktree remove --force <path>`. Removing the worktree with the link
  still in place can delete the main tree's modules through it.
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
Counts: blocker N, high N, medium N, low N, nit N
Timings: start HH:MM, first container HH:MM, last teardown HH:MM, end HH:MM

## Findings

| ID | Sev | Location | Finding | Evidence | Fix | Prevent |
|---|---|---|---|---|---|---|
| INFRA-1 | high | `nginx/...:42` | One sentence. | What you read or ran that shows it. | Concrete change. | Guard that would catch it, or "—". |

## Compared with last run
Read the most recent earlier report for this check in `temp/audits/`; if
there is none, write "First run." and nothing else here.
New: IDs. Resolved: the earlier findings that are now fixed. Recurring: IDs
also in the last report (call out any reported three times or more).

## Proposed DECISIONS.md entries
Findings that look deliberate: the entry you would add, for the user to accept or reject.

## Verified
Short bullets of important claims you checked and found true (one line each).

## Unverified / Skipped
What you could not check, and why (no deployment, Docker unavailable, ...).
```

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

When done, reply with **only**: the verdict, the counts, the top five
findings (ID, severity, one line each), and the report path. The report holds
the detail.
