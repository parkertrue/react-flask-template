---
name: audit-scaffold
description: Prove the template scaffolds cleanly - in a throwaway git worktree, follow README's "Starting a New App" steps literally, replace the notes example with a tiny feature, and check lint, tests, build and migrations still pass. Reports every step that was wrong, missing or harder than it should be.
disable-model-invocation: true
context: fork
---

# /audit-scaffold

First read `.claude/skills/_audit-shared/RULES.md` and follow it throughout
(especially the worktree notes under **Environment**). Then read `CLAUDE.md`,
`README.md`'s "Starting a New App" section, and `DECISIONS.md` from the
same folder as RULES.md. This check runs Docker: record all four Timings
(RULES.md, Report).

The template's promise is that a new app starts by renaming notes into its
first feature (or deleting it) and renaming a few things. This check acts it out. Everything happens in a
scratch worktree. Never modify the main working tree.

## 1. Set up

`git worktree add <scratch>/scaffold HEAD`, link the backend venv and
frontend modules as RULES.md describes, and confirm that lint and unit tests
pass in the worktree before changing anything (baseline).

## 2. Follow the steps literally

Carry out README's **Starting a New App** steps in order, exactly as
written, as a developer who knows only what the docs say. Create files with the
Write tool, not shell heredocs (Git Bash mangles backslashes and backticks).

**Checkpoint after every step, before fixing anything:** run ruff, ESLint and
both unit suites, and record the failure counts. Then fix what the step left
broken. For each step, record:
- whether every file, symbol and command it names exists,
- the failures at its checkpoint, and what you had to do that the step does
  not say (each one is a finding),
- files touched that the step names vs. files it doesn't.

When the example is replaced (after steps 2–3), also look for tests that
**still pass but no longer test anything**: tests that now hit a 404 instead
of the status they claim to check, or probe a table that no longer exists.
Shared tests that used the example as "any protected route" are the usual
cause. Then grep for leftovers (`notes?`, `Note`, `health`, excluding
`/api/health`, which is kept on purpose, and English uses such as "Note:").

**The stand-in feature:** in step 2, take the "rename it" route and turn
notes into a `bookmarks` resource (`url` and `title`, owned by a user,
cursor-paginated list, create), following the notes slice's pattern as
CLAUDE.md describes it (model, schema, routes, service, hook, page, unit
tests, and its E2E spec, ported and linted). Alternate runs may take the
"delete it" route instead, building `bookmarks` from scratch beside the
deleted example; say which route the report covers. Keep it minimal. The point is to discover what the pattern
makes hard, not to write a good feature. In step 4, generate its migration as
the step says, using the test stack's `db` per RULES.md. Start that stack from
the worktree after step 1's rename and note its project name: teardown must
use the name it was started under. Afterward, reset the database
(`down -v` and up again) before the integration suite, since `flask db
migrate` leaves tables and `alembic_version` behind.

Steps 6 and 7 are part mechanical, part writing. Act out every file change
they ask for: in step 6, replace `LICENSE` and `frontend/package.json`'s
`license` with a stand-in license (MIT, held by a made-up name) and delete
`.claude/skills/audit-scaffold/` in the worktree; in step 7, fill in
`OPERATOR` in `frontend/src/legal.js` and `frontend/public/.well-known/security.txt`
with made-up values, as its "Before launch" list says. Skip only the
writing: rewriting README and `CLAUDE.md` (just note which of their sections
would need it, as a measure of how much is notes-specific) and the legal
pages' text.

## 3. Verify

In the worktree: `ruff check .`, the backend unit tests with coverage,
`npm run lint`, `npm run test:coverage`, and `npm run build -- --outDir <scratch>/dist`.
Each must pass, including the coverage thresholds. Then run the backend
integration suite on a fresh test stack (it includes `test_migrations.py`,
which checks the new migration against the model; to run `run_tests.sh` from
the worktree, set `VIRTUAL_ENV` and `PATH` to the main tree's venv), and the
E2E suite (`npm run test:e2e`), since the ported specs and shared helpers are
where scaffolding breaks quietly. Tear the stack down afterward.

## 4. Judge the experience

- How many files did removing the example touch, and how many had to be
  edited rather than deleted? Every edit outside the feature's own folders is
  a coupling to question: could shared code avoid knowing about the example?
- Which renames (`app`, `appdb`, `APP_NAME`, compose projects) were spread over
  more places than the steps admit?
- Could any step be replaced by a check that fails loudly (a test or lint
  rule) instead of a line in the docs? CI's Scaffold job already runs
  `.github/scripts/remove_examples.py` and then the suites: compare its
  `DELETE` and `EDITS` with what each step actually needed, and say what else
  could move into the script or a test.

Clean up: tear down any stack, remove the worktree as RULES.md describes
(unlink `node_modules` first), and delete any branch you created.

Write the report as RULES.md describes, with ID prefix `SCAF`. Add a table of
the steps with columns: step, as written, what was actually needed, verdict.
