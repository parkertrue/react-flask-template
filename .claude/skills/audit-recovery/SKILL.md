---
name: audit-recovery
description: Break a throwaway production-config stack on purpose (crashes, outages, full storage, restarts) and check the app fails safe and recovers on its own; review backup/restore and compromised-host readiness. Runs the documented restore drill.
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
and `--wait`: its mail sink (a throwaway CA, Mailpit with STARTTLS on
`edge`, `SSL_CERT_FILE` on the worker) and the breach check off included,
or the worker refuses to start and nothing can sign up. Certificates: follow RULES.md (use the `nginx/certs/` pair,
creating a self-signed one only if none exists). Write a small driver script
in the scratch directory that, against `https://localhost` (connect to
127.0.0.1 with SNI and Host `localhost`, skipping certificate checks; see
RULES.md on requests from the host), can: log in, create a note, list notes,
refresh, and call `/api/health`, timing each call. Production rate limits
apply, so **sign up a few accounts once** at the start, as RULES.md's
recipe does (the link's token from the sink's API), and reuse them; delete
the `LIMITS:*regist*` keys between batches. Login allows 20 per minute per IP; only
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
| Redis down | Queue sign-ups with the worker stopped first, then `docker stop` redis for 60s and attempt one more: it answers 503 `SERVICE_UNAVAILABLE`, timed; afterwards the queued jobs are intact and sent, the refused one not. Repeat with the worker running: does it reconnect without a restart? Per CLAUDE.md: login answers 503 (the token can't be recorded) and refresh fails closed with 503 `SERVICE_UNAVAILABLE`, not a revocation; both must answer **promptly**, within the Redis client timeouts. Time them. With a throwaway account: logout-all answers 503 (revoking the sessions is its whole effect), and account deletion answers 503 with nothing deleted (once Redis is back, the account still logs in). Existing access tokens keep working; rate limits fall back to memory, per gunicorn worker: 5 wrong passwords answer 429 on the worker that counted them, while a request landing on the other worker still gets 401. Record the user-visible effect of each answer (does the frontend end the session?). Start it again; does the app reconnect without a restart? Are sessions intact (AOF)? |
| Redis restart | `docker restart` redis. Do refresh tokens survive (persistence)? |
| Redis crash | `docker kill` redis (no clean shutdown). With AOF `everysec`, up to a second of writes may be lost: does a session created just before survive? |
| Redis full | The `default` user is off, and the app's user can't run `ACL` or `INFO` (both `@dangerous`), so you can't read memory use. Fill under the app's own key pattern: `docker exec` into redis and use `redis-cli --user app` (password in your scratch env file) to write large values to `refresh_tokens:audit-fill-*` until **several writes in a row** are refused (memory hovers at the limit). Fill through one long-lived connection (pipe a stream of `SET`s into a single `redis-cli`): each short-lived `redis-cli` frees its client buffers on exit, which lets the app's small writes slip through. Large values alone stop just under the limit, so top up with shrinking ones (10 KB down to 10 B) on a second long-lived connection until login is refused. Before filling, log in and keep that refresh token: under OOM, login and refresh answer 503 (the rotation script writes first), the saved token's refresh too, as in a Redis outage, while logout still works. Probe login, refresh with the saved token, and logout; once the fill is gone, the saved token must refresh. Avoid logout-all, which wipes the test sessions. Try a sign-up too: the first may queue, then 503; can the worker still fetch while Redis is full? Delete the fill keys and confirm login works again. |
| MySQL hang | `docker pause` db for 60s, the most damaging DB failure. What do clients see, how long do threads stay blocked, and do healthchecks notice? Unpause and recheck. |
| MySQL down | `docker stop` db for 60s. A sign-up answers 202, and its job retries until MySQL is back. Requests needing the DB fail fast with the API's error shape, not hang. Record what `/api/health` and the Docker healthchecks say during the outage (does anything tell an operator the DB is down?). Start it again; do pooled connections recover (pre-ping) without a backend restart? |
| MySQL restart | `docker restart` db. Is data intact? |
| Disk full | In a second short run, give `db` a size-limited `tmpfs` for its data directory (a fresh MySQL 8.4 data dir is about 209 MB; allow ~260 MB) via an override (`volumes: !override` listing only the `./db/init` mount, so the app's user is still created, plus `tmpfs`), then fill it from inside the container with a throwaway file (`MSYS_NO_PATHCONV=1` from Git Bash on the `docker exec` lines and on any probe script given `/api/...` paths, and only there: exported for the whole shell, it breaks the `--env-file` paths given to compose). With the binary log off, writes that need new space should fail at once (a 503) and none commit later; record any that stall. "Remove the cause" by deleting the filler file, not via SQL. Record what clients and healthchecks see. Redis AOF and log volumes filling are reviewed on paper only. |
| nginx restart | `docker restart` nginx. Brief outage only; no config errors in logs. |
| Whole stack restart | With a job queued (worker stopped), `docker compose ... stop` then `start`, simulating a host reboot. Is the job sent once? Does everything come back, with data and sessions intact? Does `migrate` re-run harmlessly? (After a real reboot, restart policies start containers without honoring `depends_on`; that can't be tested safely on Docker Desktop, so review it on paper.) |
| Credential change | Follow `docs/deployment.md`'s "Changing a Value Later" in the scratch env file. First edit `DB_PASSWORD` alone and `up -d`: expect `up -d` to fail at `migrate` within seconds (it reads the app user's grants) and the app down, every request a 502 or 504. Restore, then edit `DB_MIGRATION_PASSWORD` alone: expect `up -d` to fail at `migrate` while the running app keeps serving; then the same with a backend change too (a label override): expect the app down. Then repeat it the way `deploy.sh` deploys, which cannot run here (it uses `.env.prod` and the clone's checkout; never run it in the main tree): `up -d --no-build --wait db redis`, then `up --no-build --no-deps --exit-code-from migrate migrate`, then, only if that succeeds, `up -d --no-build --no-deps --wait backend` and the same for `nginx`, all with `-p app_audit` and the scratch env file. With that bad password and the backend change, expect `db` to be recreated (its environment changed; `docs/deployment.md`, Redeploying, step 3), then the run to stop at `migrate` while the old backend keeps serving once MySQL is back. Include the worker in that sequence, after the backend and before nginx. Then follow its procedure for each of those, and for a new `REDIS_PASSWORD`, `REDIS_WORKER_PASSWORD` (with a job queued), the `EMAIL_URL` credentials, and `SECRET_KEY` (with a sign-up link pending: it must then answer `LINK_INVALID`), with `up -d --wait`, probing at once after `--wait` returns. Does each behave as expected? Renaming `DB_USER`, `DB_MIGRATION_USER` or `DB_NAME` is not covered there: list it under *Unverified*. |
| Bad deploy | Recreate the backend with a startup failure that needs no code change: a `SECRET_KEY` under 32 characters in the scratch env file (`up -d --force-recreate backend`). Does it refuse to start, does nginx answer with the JSON 5xx body, and does restoring the key bring it back? Run both variants: without `--no-deps`, `migrate` refuses first and the backend stays `Created`; with `--no-deps` (as `deploy.sh` replaces it), the backend itself crash-loops. Then a worker that refuses its settings (`EMAIL_URL=smtp://...`, which production refuses), through the deploy sequence: it must stop at the worker, the backend serving. |
| Worker crash | Crash it while sign-ups are queued, from the host's PID namespace, since its PID 1 (Python) ignores SIGQUIT and stops cleanly on SIGTERM or SIGINT: `docker run --rm --pid=host --entrypoint python <backend image> -c "import os; os.kill(<the worker's docker inspect .State.Pid>, 9)"`: does the restart policy bring it back, and does the queue drain? Then `docker kill` it: Docker leaves it stopped; does `up -d --wait worker` drain the queue? A job running when it died is redelivered by Dramatiq's upkeep: when, and is its email sent once? |
| Mail server unreachable | Stop the sink, then pause it, with sign-ups queued. Do retries follow the documented backoff (first after 15 to 30 s), is nothing dead-lettered early, and is each email delivered exactly once when the sink returns? Grep the worker's log: no address in it. |
| Worker stopped mid-job | `docker stop` the worker while a job waits on a paused sink, once unpausing within its 25 s drain and once not. Is the email sent exactly once either way? |

Also read the logs (`docker compose ... logs`) after each drill: are
failures logged clearly enough that an operator would know what happened?

Tear the stack down (`down -v`) when finished, even if a drill failed.

## 2. review: readiness on paper

- **Backups and restore:** `docs/deployment.md`, "Backups and Restoring",
  gives the dump and both restores; scheduling and off-host copies are left
  to other tools (DECISIONS.md, "Generic server operations are out of
  scope"). Follow it exactly on the `app_audit` stack, with `-p app_audit`
  and the scratch env file added to each command: seed data through the
  driver script, dump, change data, restore into the running stack, then
  `down -v` and restore into a fresh volume, running the driver script
  after each. Seed enough rows that the dump takes a few seconds, delete
  one account while it runs and one after it, and follow "Deleted accounts
  come back": both must stay deleted after each restore. Does each restore
  bring back the dump's rows and only those, and is a token of an account
  created after the dump refused, even once the next account registered
  takes its id? Review the rest on paper: what Redis loses
  (sessions, rate-limit counters, used sign-up links, queued and failed
  jobs), what its on-disk log and `dump.rdb` hold (job recipients until the
  log compacts, `docs/personal-data.md`), the dump's handling (it holds emails and
  password hashes), and the 3-2-1 rule.
- **Compromised host:** if an attacker gets a shell in each container (nginx,
  backend, worker, db, redis) or on the host, what can they reach and what
  must be rotated? Is the rotation procedure documented (SECRET_KEY
  invalidates all tokens and unused sign-up links; the DB passwords and both
  Redis users'; the SMTP credentials, which only the worker holds; TLS key)? Is there a way to revoke every
  session at once?
- **Operator documentation:** do README and `docs/deployment.md` tell an operator how to restart,
  roll back a bad deploy, back up and restore, rotate secrets, and read
  logs? Certificate renewal waits for a real deployment
  (DECISIONS.md, Known gaps), so a missing renewal step is a finding only
  where the docs present it as covered, or give one that is wrong.

## Out of scope
Fixing anything. Live production drills: drills never run against a
deployed server (RULES.md).

Write the report as RULES.md describes, with ID prefix `REC`. Include a table
of the drills with columns: drill, during, recovered (yes/no, time), data
lost, verdict.
