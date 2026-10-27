---
name: audit
description: Run a tier of the /audit-* checks (daily, periodic, ops, release) as parallel subagents and merge their reports into one prioritized summary with a READY or BLOCKED verdict.
argument-hint: "<daily|periodic|ops|release> [check ...]"
disable-model-invocation: true
---

# /audit

Runs several audit checks and merges their results. Each check is defined in
`.claude/skills/<check>/SKILL.md` and follows
`.claude/skills/_audit-shared/RULES.md`. The user invoking `/audit` is their
explicit request to run every check in the chosen tier, so launch them as
described below.

## Tiers

| Tier | Checks | When |
|---|---|---|
| `daily` | audit-infra | Every day, or after any config or infra change |
| `periodic` | audit-tests, audit-security, audit-code, audit-a11y, audit-docs, audit-scaffold | Every week or two, and after any feature lands |
| `ops` | audit-security, audit-recovery | Monthly, and after infra or deployment changes |
| `release` | every check above, plus audit-legal | Before tagging a release or publishing the template |

`audit-legal` runs only in `release`, or on its own (`/audit-legal`) after a
change that collects new personal data, adds a third-party service, or adds
a dependency.

**Arguments:** `$ARGUMENTS`. The first word is the tier. Any further words
name individual checks to run instead of the tier's list (for example
`/audit periodic audit-code audit-docs`). With no arguments, show the table
above and ask which tier to run. Do not guess.

## Running

1. Record the commit (`git rev-parse --short HEAD`, branch, and whether the
   tree is clean). If Docker is not running (`docker info`), tell the user that
   the Docker-dependent parts will be reported as skipped, and continue.
2. Split the tier's checks into two groups:
   - **No Docker:** audit-code, audit-docs, audit-tests, audit-legal.
   - **Docker** (they share the test or production-config stack, which only
     one may use at a time): audit-infra, audit-security, audit-a11y,
     audit-scaffold, audit-recovery, in that order.
3. Launch every check in the no-Docker group at once, plus the **first**
   check of the Docker group, each as a background `general-purpose` subagent.
   When a Docker check finishes, launch the next one. Never run two Docker
   checks at once. Prompt each subagent with:

   > You are running the `<check>` audit check, which the user started through
   > `/audit <tier>`. Read `.claude/skills/<check>/SKILL.md` and carry it out
   > exactly, with an empty scope (cover everything), following
   > `.claude/skills/_audit-shared/RULES.md`. <For the no-Docker group, add:
   > "Start no containers in this run; other checks are using Docker. Read-only
   > Docker commands are fine (RULES.md). List any step that needs a running
   > stack under Unverified / Skipped.">
   > Write your report to `temp/audits/` as RULES.md says, and reply with only
   > the summary RULES.md asks for.

4. While they run, tell the user what is running and what is queued. Do not
   predict results.

## Consolidating

When every check has finished, read each check's report file (not just the
summary it returned) and write `temp/audits/YYYY-MM-DD-audit-<tier>.md`:

```markdown
# Audit (<tier>) — YYYY-MM-DD

Commit: <sha> (<branch>), clean|dirty
Verdict: READY | BLOCKED — N blockers
Checks: <check>: <verdict> (<report file>), ...

## Blockers
## High
## Medium
## Low and nits
(one line each: ID, location, finding, fix; link the check's report)

## Cross-check themes
Problems reported by more than one check, merged into one item, and patterns
(for example, several findings with the same root cause).

## Proposed guards
Every finding's Prevent column, deduplicated: lint rules, tests or CI jobs
that would stop these coming back, in priority order.

## Proposed DECISIONS.md entries
Collected from every check, for the user to accept or reject.

## Skipped
What no check could cover in this run, and why.

## Timings
| Check | Start | First container | Last teardown | End | Minutes using Docker | Minutes in all |
|---|---|---|---|---|---|---|
(one row per check, from its report's Timings line; for a no-Docker check,
leave the container columns empty)
```

The verdict is BLOCKED if any check found a blocker, or any check could not
run at all.

Then reply to the user with: the verdict, counts by severity, the blockers and
high findings (one line each), the top proposed guards, and the path to the
consolidated report. Do not fix anything. Ask which findings to address, and
whether to record the proposed DECISIONS.md entries.
