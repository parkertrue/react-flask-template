---
name: audit-recovery
description: Break a throwaway production-config stack on purpose (crashes, outages, full storage, restarts) and check the app fails safe and recovers on its own; review backup/restore and compromised-host readiness. Restore drills run once backups exist.
argument-hint: "[drills|review]"
disable-model-invocation: true
context: fork
---

# /audit-recovery

First read `.claude/skills/_audit-shared/RULES.md` and follow it throughout,
especially **Boundaries**: this check uses the production-config stack
(`-p app_audit`). Then read `CLAUDE.md`, plus `SOURCES.md` (its "Start with"
table's `/audit-recovery` row, and the Redis, MySQL, architecture and ops
sections it points to) and `DECISIONS.md` from the same folder as RULES.md.

This check takes about 30 minutes. Give long commands explicit timeouts, and
wait with until-loops that have deadlines (RULES.md). It runs Docker: record
all four Timings (RULES.md, Report).

Build the scratch env file from `.env.prod.example` and keep its
`COMPOSE_PROFILES`: the bundled `db` and `redis` run only under it.

**Scope:** `$ARGUMENTS`. If empty, run both parts.

## 1. drills: failure injection

Set up the production-config stack as RULES.md describes, with `--build`
and `--wait`. Certificates: follow RULES.md (use the `nginx/certs/` pair,
creating a self-signed one only if none exists). Write a small driver script
in the scratch directory that, against `https://localhost` (connect to
127.0.0.1 with SNI and Host `localhost`, skipping certificate checks; see
RULES.md on requests from the host), can: log in, create a note, list notes,
refresh, and call `/api/health`, timing each call. Production rate limits
apply: register allows 10 per hour per IP, so **register a few accounts
once** at the start and reuse them. Login allows 20 per minute per IP; only
failed logins count toward its per-account limits (5 a minute per account
and IP, 100 an hour per account), so the driver must never send a wrong
password except in a probe meant to. Refresh allows 10 per minute per user:
rotate refreshes across the accounts. Run the driver once to establish the
baseline.

For each drill: record what the user sees **during** the failure (status
codes and bodies of the driver's calls), whether the stack **recovers on its
own** once the cause is removed (and how long it takes), and whether any data
or session was **lost or corrupted**. Then reset to a healthy stack before the
next drill. Expected behavior comes from CLAUDE.md: if it promises something
(fail closed, fail fast, rate limits fall back to memory), test exactly
that. Also, for every write that got an error or timeout during a drill,
check afterward whether it committed anyway: a client told "failed" that
retries will create duplicates.

| Drill | How |
|---|---|
| Backend crash | Crash the process from inside, since Docker treats `docker kill` as a manual stop and `unless-stopped` then never restarts it: `docker exec <backend> python -c "import os,signal; os.kill(1, signal.SIGQUIT)"` (the image has no `kill` or `ps`). Not `SIGKILL`: the kernel ignores it when sent to PID 1 from inside its own namespace, so nothing happens; gunicorn exits at once on `SIGQUIT`. Does the restart policy bring it back, and how fast? Separately, swap it several times (`up -d --force-recreate --no-deps --wait backend`) with health probed every 0.2 s: does the first 200 come as soon as `--wait` returns, at the same address (nginx connects to the backend's fixed address, `nginx/templates/00-upstream.conf.template`, with no DNS)? The credential-change row's `REDIS_PASSWORD` rotation, which recreates redis and the backend together, is the same check under a full `up -d`. |
| Backend hang | `docker pause` the backend for 60s. What do clients see, and how fast (nginx timeouts)? Unpause and recheck. |
| Redis down | `docker stop` redis for 60s. Per CLAUDE.md: login answers 503 (the token can't be recorded) and refresh fails closed with 503 `SERVICE_UNAVAILABLE`, not a revocation; both must answer **promptly**, within the Redis client timeouts. Time them. With a throwaway account: logout-all answers 503 (revoking the sessions is its whole effect), and account deletion answers 503 with nothing deleted (once Redis is back, the account still logs in). Existing access tokens keep working; rate limits fall back to memory, per gunicorn worker: 5 wrong passwords answer 429 on the worker that counted them, while a request landing on the other worker still gets 401. Record the user-visible effect of each answer (does the frontend end the session?). Start it again; does the app reconnect without a restart? Are sessions intact (AOF)? |
| Redis restart | `docker restart` redis. Do refresh tokens survive (persistence)? |
| Redis crash | `docker kill` redis (no clean shutdown). With AOF `everysec`, up to a second of writes may be lost: does a session created just before survive? |
| Redis full | The `default` user is off, and the app's user can't run `ACL` or `INFO` (both `@dangerous`), so you can't read memory use. Fill under the app's own key pattern: `docker exec` into redis and use `redis-cli --user app` (password in your scratch env file) to write large values to `refresh_tokens:audit-fill-*` until **several writes in a row** are refused (memory hovers at the limit). Fill through one long-lived connection (pipe a stream of `SET`s into a single `redis-cli`): each short-lived `redis-cli` frees its client buffers on exit, which lets the app's small writes slip through. Large values alone stop just under the limit, so top up with shrinking ones (10 KB down to 10 B) on a second long-lived connection until login is refused. Before filling, log in and keep that refresh token, since rotation still works under OOM (its script deletes first). Probe login, refresh with the saved token, and logout. Avoid logout-all, which wipes the test sessions. Delete the fill keys and confirm login works again. |
| MySQL hang | `docker pause` db for 60s, the most damaging DB failure. What do clients see, how long do threads stay blocked, and do healthchecks notice? Unpause and recheck. |
| MySQL down | `docker stop` db for 60s. Requests needing the DB fail fast with the API's error shape, not hang. Record what `/api/health` and the Docker healthchecks say during the outage (does anything tell an operator the DB is down?). Start it again; do pooled connections recover (pre-ping) without a backend restart? |
| MySQL restart | `docker restart` db. Is data intact? |
| Disk full | In a second short run, give `db` a size-limited `tmpfs` for its data directory (a fresh MySQL 8.4 data dir is about 209 MB; allow ~260 MB) via an override (`volumes: !reset []` plus `tmpfs`), then fill it from inside the container with a throwaway file (`MSYS_NO_PATHCONV=1` on the `docker exec` lines from Git Bash, and only there: exported for the whole shell, it breaks the `--env-file` paths given to compose). Writes may hang rather than fail; "remove the cause" by deleting the filler file, not via SQL. Record what clients and healthchecks see. Teardown: if this run starts on top of an existing stack, `down -v` misses the named `db_data` volume hidden by the override, so remove `app_audit_db_data` by hand; starting after `down -v` of the first run never creates it. Redis AOF and log volumes filling are reviewed on paper only. |
| nginx restart | `docker restart` nginx. Brief outage only; no config errors in logs. |
| Whole stack restart | `docker compose ... stop` then `start`, simulating a host reboot. Does everything come back, with data and sessions intact? Does `migrate` re-run harmlessly? (After a real reboot, restart policies start containers without honoring `depends_on`; that can't be tested safely on Docker Desktop, so review it on paper.) |
| Credential change | Follow README's "Changing a value later" in the scratch env file. First edit `DB_PASSWORD` alone and `up -d`: expect the app locked out (every request a 502). Restore, then edit `DB_MIGRATION_PASSWORD` alone: expect `up -d` to fail at `migrate` while the running app keeps serving. Then follow README's procedure for each, and for a new `REDIS_PASSWORD` and `SECRET_KEY`, with `up -d --wait`, probing at once after `--wait` returns. Does each behave as expected? Renaming `DB_USER`, `DB_MIGRATION_USER` or `DB_NAME` is not covered by README: list it under *Unverified*. |
| Bad deploy | Recreate the backend with a startup failure that needs no code change: a `SECRET_KEY` under 32 characters in the scratch env file (`up -d --force-recreate backend`). Does it refuse to start, does nginx answer with the JSON 5xx body, and does restoring the key bring it back? |

Also read the logs (`docker compose ... logs`) after each drill: are
failures logged clearly enough that an operator would know what happened?

Tear the stack down (`down -v`) when finished, even if a drill failed.

## 2. review: readiness on paper

- **Backups and restore:** DECISIONS.md lists backups as a known gap. Until a
  backup procedure exists, report "Restore drill: blocked, no backups" under
  *Skipped*, and review only what a backup would need: which volumes hold
  state (MySQL, Redis AOF), what can be lost without harm (rate-limit
  counters), consistent MySQL dumps (`--single-transaction`), and the 3-2-1
  rule. Once a backup procedure exists in the repo or README, this part must
  instead restore the most recent backup into a fresh `app_audit` stack and run
  the driver script against it.
- **Compromised host:** if an attacker gets a shell in each container (nginx,
  backend, db, redis) or on the host, what can they reach and what must be
  rotated? Is the rotation procedure documented (SECRET_KEY invalidates all
  tokens; DB and Redis passwords; TLS key)? Is there a way to revoke every
  session at once?
- **Operator documentation:** does README tell an operator how to restart,
  roll back a bad deploy, rotate secrets, and read logs? The runbook waits
  for the first server (DECISIONS.md, Known gaps, "README's production
  section"), so a missing runbook step is a finding only where README
  presents the step as covered, or gives one that is wrong.

## Out of scope
Fixing anything. Live production drills: there is no deployment, and drills
never run against production even once there is.

Write the report as RULES.md describes, with ID prefix `REC`. Include a table
of the drills with columns: drill, during, recovered (yes/no, time), data
lost, verdict.
